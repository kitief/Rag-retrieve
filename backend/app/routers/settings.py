"""
Settings router: the runtime knobs exposed by the in-app settings dialog.

Two groups are editable from the web UI:

* **Language** — the deployment default used when a visitor has not picked one
  explicitly in the language switcher (``app_language``).
* **API** — the cloud LLM endpoint (``llm_provider`` / ``llm_base_url`` /
  ``llm_model`` / ``llm_api_key``).

Values are stored in the ``app_settings`` table so they survive restarts, and
they take precedence over the matching ``.env`` entries. The API key is write
only: the GET responses only report whether one is configured and a short hint.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import runtime_settings
from app.core.dependencies import get_current_user, get_db
from app.core.i18n import SUPPORTED_LANGUAGES, configured_language, normalize_language, t
from app.models.app_setting import AppSetting
from app.models.llm_api_key import LLMApiKey
from app.models.user import User
from app.services import llm_client

router = APIRouter(prefix="/settings", tags=["Settings"])

logger = logging.getLogger(__name__)

_LANGUAGE_KEY = "app_language"
_SECRET_KEYS = {"llm_api_key"}
_CONNECTION_KEY = "llm_connection"

# Serialises /settings/llm/test probes: each probe layers unsaved preview
# values over the runtime overrides and restores them in ``finally``, so a
# concurrent probe must not interleave that set/restore cycle.
_test_llm_lock = asyncio.Lock()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class LanguageSettings(BaseModel):
    current: str
    supported: list[str]
    source: str


class ConnectionState(BaseModel):
    """
    The last connection probe, persisted so it survives closing the dialog.

    Without this the panel forgot every successful probe the moment it was
    reopened: the model field went blank again and the user had no way to tell a
    working configuration from a broken one — even though the stored key kept
    answering questions. ``stale`` is set when the saved provider/base URL/key
    no longer match what was probed, so an old green light cannot outlive an
    edit.
    """

    ok: bool
    message: str
    provider: str
    base_url: str
    models: list[str] = []
    checked_at: str | None = None
    stale: bool = False
    key_hint: str = ""


class LLMSettings(BaseModel):
    provider: str
    base_url: str
    model: str
    api_key_set: bool
    api_key_hint: str
    timeout_seconds: float
    max_retries: int
    max_concurrency: int
    connection: ConnectionState | None = None


class ProviderInfo(BaseModel):
    name: str
    label: str
    base_url: str
    model: str
    api_key_env: str
    docs_url: str


class ApiKeyInfo(BaseModel):
    """A saved key. The secret itself is never returned — only a masked hint."""

    id: str
    provider: str
    label: str
    hint: str
    active: bool
    created_at: str | None = None


class SettingsResponse(BaseModel):
    language: LanguageSettings
    llm: LLMSettings
    providers: list[ProviderInfo]
    api_keys: list[ApiKeyInfo] = []
    restart_required: bool = False


class ApiKeyCreate(BaseModel):
    provider: str = Field(default="custom")
    label: str = Field(default="", description="Optional name shown in the dropdown.")
    value: str = Field(description="The API key itself.")
    activate: bool = Field(
        default=True,
        description="Switch the running configuration to this key right away.",
    )


class ApiKeyUpdate(BaseModel):
    label: str | None = None
    activate: bool | None = None
    value: str | None = None


class ModelsResponse(BaseModel):
    models: list[str]
    base_url: str
    source: str


class SettingsUpdate(BaseModel):
    """Every field is optional; ``None`` means "leave unchanged"."""

    language: str | None = None
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = Field(
        default=None,
        description="New API key. Send an empty string to clear the stored key.",
    )


class SettingsTestRequest(BaseModel):
    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None


class SettingsTestResponse(BaseModel):
    ok: bool
    message: str
    provider: str
    model: str
    base_url: str


class ConnectRequest(BaseModel):
    """Credentials typed into the dialog, used to probe an endpoint before saving."""

    llm_provider: str | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = None


class ConnectResponse(BaseModel):
    """Result of one connection attempt: reachable or not, plus the model list."""

    ok: bool
    message: str
    provider: str
    base_url: str
    models: list[str] = []
    source: str = "endpoint"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _mask(api_key: str) -> str:
    if not api_key:
        return ""
    tail = api_key[-4:] if len(api_key) > 8 else ""
    return f"sk-…{tail}" if tail else "sk-…"


def _provider_label(name: str) -> str:
    return {
        "deepseek": "DeepSeek",
        "openai": "OpenAI",
        "custom": "OpenAI-compatible",
    }.get(name, name.title())


async def _load_overrides(db: AsyncSession) -> dict[str, str]:
    """Read every stored override into the in-process cache."""
    return await runtime_settings.load_from_db(db)


def _language_source() -> str:
    if runtime_settings.get_override(_LANGUAGE_KEY):
        return "settings"
    if getattr(get_settings(), "app_language", None):
        return "environment"
    return "default"


async def _list_api_keys(db: AsyncSession, active_value: str) -> list[ApiKeyInfo]:
    """Return the saved keys, flagging the one the runtime is currently using."""
    result = await db.execute(select(LLMApiKey).order_by(LLMApiKey.created_at))
    rows = result.scalars().all()
    return [
        ApiKeyInfo(
            id=row.id,
            provider=row.provider,
            label=row.label or row.provider,
            hint=_mask(row.value),
            active=bool(active_value) and row.value == active_value,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in rows
    ]


async def _activate_api_key(db: AsyncSession, value: str) -> None:
    """Persist ``value`` as the active key and refresh the in-process cache."""
    existing = await db.get(AppSetting, "llm_api_key")
    if existing is None:
        db.add(AppSetting(key="llm_api_key", value=value))
    else:
        existing.value = value
    await db.commit()
    await _load_overrides(db)


async def _store_connection(db: AsyncSession, state: ConnectionState) -> None:
    """Remember the outcome of a probe so reopening the dialog shows it again."""
    payload = state.model_dump_json()
    existing = await db.get(AppSetting, _CONNECTION_KEY)
    if existing is None:
        db.add(AppSetting(key=_CONNECTION_KEY, value=payload))
    else:
        existing.value = payload
    await db.commit()


async def _read_connection(db: AsyncSession, resolved) -> ConnectionState | None:
    """
    Load the last probe, flagging it stale if the configuration has moved on.

    A stored "connected" that was recorded against a different base URL, model or
    key is actively misleading — the panel would show green while the runtime
    used something else — so it is returned with ``stale=True`` and the UI treats
    it as not connected.
    """
    row = await db.get(AppSetting, _CONNECTION_KEY)
    if row is None or not (row.value or "").strip():
        return None
    try:
        state = ConnectionState.model_validate_json(row.value)
    except Exception:  # noqa: BLE001 - a corrupt row must not break the panel
        logger.warning("[settings] stored connection state is unreadable; ignoring it")
        return None

    same_base = state.base_url.strip().rstrip("/") == (resolved.base_url or "").strip().rstrip("/")
    same_provider = state.provider == resolved.provider
    # Compare the masked tail rather than the secret: a probe recorded against a
    # different key must not keep its green light.
    same_key = (state.key_hint or "") == _mask(resolved.api_key or "")
    state.stale = not (same_base and same_provider and same_key and bool(resolved.api_key))
    return state


async def _clear_connection(db: AsyncSession) -> None:
    """Drop the remembered probe (configuration reset)."""
    existing = await db.get(AppSetting, _CONNECTION_KEY)
    if existing is not None:
        await db.delete(existing)
        await db.commit()


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("", response_model=SettingsResponse)
async def read_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Return the current runtime configuration (never the raw API key)."""
    await _load_overrides(db)
    resolved = llm_client.resolve_llm_config()
    cfg = get_settings()

    providers = [
        ProviderInfo(
            name=preset.name,
            label=_provider_label(preset.name),
            base_url=preset.base_url,
            model=preset.model,
            api_key_env=preset.api_key_env,
            docs_url=preset.docs_url,
        )
        for preset in llm_client.PROVIDER_PRESETS.values()
    ]

    return SettingsResponse(
        language=LanguageSettings(
            current=configured_language(),
            supported=list(SUPPORTED_LANGUAGES),
            source=_language_source(),
        ),
        llm=LLMSettings(
            provider=resolved.provider,
            base_url=resolved.base_url,
            model=resolved.model,
            api_key_set=bool(resolved.api_key),
            api_key_hint=_mask(resolved.api_key),
            timeout_seconds=resolved.timeout,
            max_retries=resolved.max_retries,
            max_concurrency=resolved.max_concurrency,
            connection=await _read_connection(db, resolved),
        ),
        providers=providers,
        api_keys=await _list_api_keys(db, resolved.api_key),
        restart_required=False,
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """
    Persist the settings the user changed, then apply them immediately.

    Sending ``null`` (or omitting a field) keeps the stored value; sending an
    empty string clears the override so the ``.env`` value applies again.
    """
    updates: dict[str, str] = {}

    if payload.language is not None:
        normalized = normalize_language(payload.language)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("settings.unsupported_language", languages=", ".join(SUPPORTED_LANGUAGES)),
            )
        updates[_LANGUAGE_KEY] = normalized

    if payload.llm_provider is not None:
        provider = payload.llm_provider.strip().lower()
        if provider and provider not in llm_client.PROVIDER_PRESETS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("settings.unknown_provider", providers=", ".join(llm_client.PROVIDER_PRESETS)),
            )
        updates["llm_provider"] = provider

    for field in ("llm_base_url", "llm_model", "llm_api_key"):
        value = getattr(payload, field)
        if value is not None:
            updates[field] = value.strip()

    if payload.llm_base_url is not None and payload.llm_base_url.strip():
        base_url = payload.llm_base_url.strip()
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("settings.invalid_base_url"),
            )

    for key, value in updates.items():
        existing = await db.get(AppSetting, key)
        if not value:
            if existing is not None:
                await db.delete(existing)
            continue
        if existing is None:
            db.add(AppSetting(key=key, value=value))
        else:
            existing.value = value
    await db.commit()

    await _load_overrides(db)
    return await read_settings(current_user=current_user, db=db)


@router.delete("", response_model=SettingsResponse)
async def reset_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Drop every stored override so the ``.env`` configuration applies again."""
    await db.execute(delete(AppSetting))
    await db.commit()
    await _load_overrides(db)
    return await read_settings(current_user=current_user, db=db)


@router.post("/llm/test", response_model=SettingsTestResponse)
async def test_llm(
    payload: SettingsTestRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsTestResponse:
    """
    Probe the configured endpoint with the currently *saved* credentials.

    The body is accepted so the dialog can also test values before saving, but
    nothing is persisted here.
    """
    await _load_overrides(db)
    saved = runtime_settings.snapshot()

    preview: dict[str, str] = {}
    if payload is not None:
        for field in ("llm_provider", "llm_base_url", "llm_model", "llm_api_key"):
            value = getattr(payload, field)
            if value is not None and value.strip():
                preview[field] = value.strip()

    async with _test_llm_lock:
        ok = False
        try:
            if preview:
                # Layer the unsaved values on top of the stored configuration.
                runtime_settings.set_overrides({**saved, **preview})
            resolved = llm_client.resolve_llm_config()
            ok = await llm_client.check_llm_availability()
        finally:
            if preview:
                runtime_settings.clear_overrides()
                runtime_settings.set_overrides(saved)

    return SettingsTestResponse(
        ok=ok,
        message=(
            t("settings.test_ok")
            if ok
            else t("settings.test_failed", model=resolved.model, base_url=resolved.base_url)
        ),
        provider=resolved.provider,
        model=resolved.model,
        base_url=resolved.base_url,
    )


# ─── Model discovery ─────────────────────────────────────────────────────────

@router.post("/llm/connect", response_model=ConnectResponse)
async def connect_llm(
    payload: ConnectRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ConnectResponse:
    """
    Probe an endpoint with the credentials typed into the dialog.

    This is the "Connect" button: it validates the base URL and the key against
    ``GET /models`` and hands back the model list so the dialog can fill its
    dropdown. The model field stays empty until this succeeds — that is what
    keeps a stale name from being saved by accident.

    The *outcome* is persisted (never the key) so reopening the dialog restores
    the same badge and model list. Without that, a user who had a working
    configuration saw a blank panel every time and had no way to tell whether
    anything was actually connected.

    When the request omits the key, the one already stored is used, so a user who
    only changes the base URL does not have to retype the secret.
    """
    await _load_overrides(db)
    saved = llm_client.resolve_llm_config()

    provider = (payload.llm_provider or saved.provider or "custom").strip().lower()
    base_url = (payload.llm_base_url or saved.base_url or "").strip().rstrip("/")
    api_key = (payload.llm_api_key or saved.api_key or "").strip()

    def _fail(message: str) -> ConnectResponse:
        return ConnectResponse(
            ok=False, message=message, provider=provider, base_url=base_url
        )

    if not base_url:
        return _fail(t("settings.connect_missing_base_url"))
    if not base_url.startswith(("http://", "https://")):
        return _fail(t("settings.invalid_base_url"))
    if not api_key:
        return _fail(t("settings.connect_missing_key"))

    try:
        models = await llm_client.fetch_models(base_url, api_key)
    except (llm_client.LLMConfigurationError, llm_client.LLMRequestError) as exc:
        logger.info("[settings] connect probe failed: %s", exc)
        failure = _fail(t("settings.connect_failed", message=str(exc)[:300]))
        await _store_connection(
            db,
            ConnectionState(
                ok=False,
                message=failure.message,
                provider=provider,
                base_url=base_url,
                key_hint=_mask(api_key),
                checked_at=datetime.now(timezone.utc).isoformat(),
            ),
        )
        return failure

    if models:
        message = t("settings.connect_ok", count=len(models))
    else:
        message = t("settings.connect_no_models")
    await _store_connection(
        db,
        ConnectionState(
            ok=True,
            message=message,
            provider=provider,
            base_url=base_url,
            models=models,
            key_hint=_mask(api_key),
            checked_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    return ConnectResponse(
        ok=True,
        message=message,
        provider=provider,
        base_url=base_url,
        models=models,
        source="endpoint",
    )


@router.get("/llm/models", response_model=ModelsResponse)
async def list_llm_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModelsResponse:
    """
    Return the model ids the configured endpoint advertises (``GET /models``).

    The dialog uses this to populate a model dropdown. Providers that do not
    implement the endpoint yield an empty list and the dialog falls back to a
    free-text field.
    """
    await _load_overrides(db)
    resolved = llm_client.resolve_llm_config()
    try:
        models = await llm_client.list_models()
        source = "endpoint"
    except (llm_client.LLMConfigurationError, llm_client.LLMRequestError) as exc:
        logger.info("[settings] model list unavailable: %s", exc)
        models = []
        source = "unavailable"

    return ModelsResponse(models=models, base_url=resolved.base_url, source=source)


# ─── Saved API keys ──────────────────────────────────────────────────────────

@router.post("/llm/keys", response_model=ApiKeyInfo, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyInfo:
    """Store a new key (optionally making it the active one immediately)."""
    value = payload.value.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=t("settings.api_key_required"),
        )

    provider = payload.provider.strip().lower() or "custom"
    if provider not in llm_client.PROVIDER_PRESETS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=t("settings.unknown_provider", providers=", ".join(llm_client.PROVIDER_PRESETS)),
        )

    row = LLMApiKey(provider=provider, label=payload.label.strip(), value=value)
    db.add(row)
    await db.commit()
    await db.refresh(row)

    if payload.activate:
        await _activate_api_key(db, value)

    active = (runtime_settings.get_override("llm_api_key") or get_settings().llm_api_key or "")
    return ApiKeyInfo(
        id=row.id,
        provider=row.provider,
        label=row.label or row.provider,
        hint=_mask(row.value),
        active=row.value == active,
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.patch("/llm/keys/{key_id}", response_model=SettingsResponse)
async def update_api_key(
    key_id: str,
    payload: ApiKeyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Rename a key, replace its secret, or make it the active key."""
    row = await db.get(LLMApiKey, key_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("settings.api_key_not_found"),
        )

    if payload.label is not None:
        row.label = payload.label.strip()
    if payload.value is not None:
        value = payload.value.strip()
        if not value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=t("settings.api_key_required"),
            )
        row.value = value
    await db.commit()

    if payload.activate:
        await db.refresh(row)
        await _activate_api_key(db, row.value)

    await _load_overrides(db)
    return await read_settings(current_user=current_user, db=db)


@router.delete("/llm/keys/{key_id}", response_model=SettingsResponse)
async def delete_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SettingsResponse:
    """Forget a saved key. Deleting the active key leaves the runtime untouched."""
    row = await db.get(LLMApiKey, key_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("settings.api_key_not_found"),
        )
    await db.delete(row)
    await db.commit()
    await _load_overrides(db)
    return await read_settings(current_user=current_user, db=db)

