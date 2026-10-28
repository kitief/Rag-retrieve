"""
Runtime settings overrides.

Built-in defaults come from environment variables (`.env` ->
`app.config.Settings`). The settings dialog in the web UI lets a user override a
few of them at runtime without editing files; those overrides are persisted in
the ``app_settings`` table and cached here in memory so the hot paths
(`resolve_llm_config`, `i18n.configured_language`) stay synchronous.

Precedence is: runtime override > environment variable > built-in default.
"""
from __future__ import annotations

OVERRIDABLE_KEYS = (
    "llm_provider",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "app_language",
)

_overrides: dict[str, str] = {}


def get_override(key: str) -> str | None:
    """Return the runtime override for ``key`` (``None`` when unset)."""
    return _overrides.get(key)


def set_overrides(values: dict[str, str]) -> None:
    """Merge ``values`` into the cache; an empty value clears the override."""
    for key, value in values.items():
        if key not in OVERRIDABLE_KEYS:
            continue
        cleaned = (value or "").strip()
        if cleaned:
            _overrides[key] = cleaned
        else:
            _overrides.pop(key, None)


def clear_overrides(keys: list[str] | None = None) -> None:
    """Drop one, several or all overrides so the env defaults apply again."""
    if keys is None:
        _overrides.clear()
        return
    for key in keys:
        _overrides.pop(key, None)


def snapshot() -> dict[str, str]:
    """Copy of the current overrides, safe to hand to the API layer."""
    return dict(_overrides)


async def load_from_db(session) -> dict[str, str]:
    """
    Refresh the in-process cache from the ``app_settings`` table.

    Called once at startup and after every write, so the synchronous hot paths
    (``resolve_llm_config``, ``i18n.configured_language``) never hit the DB.
    """
    from sqlalchemy import select

    from app.models.app_setting import AppSetting

    result = await session.execute(select(AppSetting))
    stored = {row.key: (row.value or "") for row in result.scalars().all()}
    _overrides.clear()
    set_overrides(stored)
    return dict(_overrides)
