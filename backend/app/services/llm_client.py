"""
Cloud LLM client (OpenAI-compatible Chat Completions API).

This module is the single place where the application talks to a remote
large-language-model provider. It replaces the previous local-inference
stack (llama.cpp server / Ollama daemon):

  * Default provider is DeepSeek (https://api.deepseek.com/v1).
  * Any other OpenAI-compatible endpoint can be used by setting
    ``LLM_PROVIDER=custom`` plus ``LLM_BASE_URL`` / ``LLM_MODEL``.

Only the chat/generation workloads go through here. Document embedding
still runs locally through FastEmbed (``app/utils/embedder.py``).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Mapping, Sequence

import httpx

from app.core.i18n import t

logger = logging.getLogger(__name__)


# ─── Provider presets ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderPreset:
    """Static defaults for a well-known OpenAI-compatible provider."""

    name: str
    base_url: str
    model: str
    api_key_env: str
    docs_url: str


PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        name="deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        docs_url="https://platform.deepseek.com/api_keys",
    ),
    "openai": ProviderPreset(
        name="openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
        api_key_env="OPENAI_API_KEY",
        docs_url="https://platform.openai.com/api-keys",
    ),
    "custom": ProviderPreset(
        name="custom",
        base_url="",
        model="",
        api_key_env="LLM_API_KEY",
        docs_url="",
    ),
}

DEFAULT_PROVIDER = "deepseek"


class LLMConfigurationError(RuntimeError):
    """Raised when the provider/endpoint/model configuration is unusable."""


class LLMRequestError(RuntimeError):
    """Raised when the remote provider rejects or fails a request."""


# ─── Resolved configuration ──────────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedLLMConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_retries: int
    max_concurrency: int

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def resolve_llm_config() -> ResolvedLLMConfig:
    """
    Build the effective LLM configuration from settings + provider preset.

    Precedence: explicit ``LLM_BASE_URL`` / ``LLM_MODEL`` values in the
    environment win over the provider preset, which in turn is only a default.
    """
    from app.config import get_settings

    cfg = get_settings()

    provider = (cfg.llm_provider or DEFAULT_PROVIDER).strip().lower()
    preset = PROVIDER_PRESETS.get(provider)

    if preset is None:
        # Unknown provider name: treat it as a custom OpenAI-compatible endpoint.
        logger.warning(
            "[LLM] Unknown LLM_PROVIDER '%s'; falling back to custom endpoint mode.",
            provider,
        )
        preset = PROVIDER_PRESETS["custom"]
        provider = "custom"

    base_url = (cfg.llm_base_url or "").strip() or preset.base_url
    model = (cfg.llm_model or "").strip() or preset.model

    api_key = (cfg.llm_api_key or "").strip()

    return ResolvedLLMConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        model=model,
        timeout=float(cfg.llm_timeout_seconds),
        max_retries=max(1, int(cfg.llm_max_retries)),
        max_concurrency=max(1, int(cfg.llm_max_concurrency)),
    )


def describe_llm_setup() -> str:
    """Human-readable one-liner used by the startup self-check."""
    try:
        resolved = resolve_llm_config()
    except Exception as exc:  # pragma: no cover - defensive
        return f"LLM configuration could not be resolved: {exc}"

    key_state = "set" if resolved.api_key else "MISSING"
    return (
        f"provider={resolved.provider} model={resolved.model} "
        f"base_url={resolved.base_url} api_key={key_state}"
    )


# ─── Concurrency guard ───────────────────────────────────────────────────────

_semaphores: dict[int, asyncio.Semaphore] = {}


def _get_semaphore(limit: int) -> asyncio.Semaphore:
    """
    Return a lazily-created semaphore for the running event loop.

    Cloud endpoints handle parallel requests well, so this is only a safety
    valve against runaway fan-out (quiz batches, notes pages), not the CPU
    serialization the old local-inference gate enforced.
    """
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    semaphore = _semaphores.get(loop_id)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _semaphores[loop_id] = semaphore
    return semaphore


# ─── Request helpers ─────────────────────────────────────────────────────────

def _headers(resolved: ResolvedLLMConfig) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {resolved.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _ensure_configured(resolved: ResolvedLLMConfig) -> None:
    if not resolved.base_url or not resolved.model:
        raise LLMConfigurationError(
            "LLM endpoint is not configured. Set LLM_BASE_URL and LLM_MODEL "
            "(or pick a known LLM_PROVIDER such as 'deepseek')."
        )
    if not resolved.api_key:
        preset = PROVIDER_PRESETS.get(resolved.provider)
        hint = f" Get a key at {preset.docs_url}." if preset and preset.docs_url else ""
        raise LLMConfigurationError(
            "LLM_API_KEY is empty, so no request can be authorized." + hint
            + " After adding the key, restart the backend container."
        )


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return response.text[:400] if response.text else "(empty body)"

    if isinstance(payload, Mapping):
        error = payload.get("error")
        if isinstance(error, Mapping):
            message = error.get("message") or error.get("type") or error
            return str(message)[:400]
        if error:
            return str(error)[:400]
        if payload.get("message"):
            return str(payload["message"])[:400]
    return str(payload)[:400]


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


# ─── Non-streaming completion ────────────────────────────────────────────────

async def chat_completion(
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    json_mode: bool = False,
    timeout: float | None = None,
) -> str:
    """
    Call the remote chat-completions endpoint and return the assistant text.

    Retries transient failures (rate limits, 5xx, connection errors) with
    exponential backoff. Raises ``LLMConfigurationError`` when credentials or
    the endpoint are missing, and ``LLMRequestError`` when the provider keeps
    failing.
    """
    resolved = resolve_llm_config()
    _ensure_configured(resolved)

    payload: dict[str, Any] = {
        "model": resolved.model,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    effective_timeout = timeout or resolved.timeout
    last_error: str = ""

    async with _get_semaphore(resolved.max_concurrency):
        for attempt in range(1, resolved.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=effective_timeout) as client:
                    response = await client.post(
                        resolved.chat_completions_url,
                        headers=_headers(resolved),
                        json=payload,
                    )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "[LLM] transport error (attempt %d/%d): %s",
                    attempt,
                    resolved.max_retries,
                    last_error,
                )
            else:
                if response.status_code == 200:
                    return _parse_completion_text(response)

                last_error = (
                    f"HTTP {response.status_code}: {_extract_error_detail(response)}"
                )
                if not _retryable_status(response.status_code):
                    raise LLMRequestError(
                        f"LLM provider '{resolved.provider}' rejected the request "
                        f"({last_error})."
                    )
                logger.warning(
                    "[LLM] provider error (attempt %d/%d): %s",
                    attempt,
                    resolved.max_retries,
                    last_error,
                )

            if attempt < resolved.max_retries:
                await asyncio.sleep(min(2 ** (attempt - 1), 8))

    raise LLMRequestError(
        f"LLM provider '{resolved.provider}' failed after "
        f"{resolved.max_retries} attempts: {last_error}"
    )


def _parse_completion_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except Exception as exc:
        raise LLMRequestError(f"LLM returned non-JSON body: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMRequestError(
            f"Unexpected LLM response shape: {str(data)[:300]}"
        ) from exc

    if content is None:
        return ""
    return str(content)


# ─── Streaming completion ────────────────────────────────────────────────────

async def stream_chat_completion(
    messages: Sequence[Mapping[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream assistant tokens from the remote provider as plain text chunks.

    Yields text deltas. Raises ``LLMConfigurationError`` / ``LLMRequestError``
    so callers can render a friendly message into the SSE stream.
    """
    resolved = resolve_llm_config()
    _ensure_configured(resolved)

    payload: dict[str, Any] = {
        "model": resolved.model,
        "messages": [dict(message) for message in messages],
        "temperature": temperature,
        "stream": True,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async with _get_semaphore(resolved.max_concurrency):
        async with httpx.AsyncClient(timeout=resolved.timeout) as client:
            try:
                async with client.stream(
                    "POST",
                    resolved.chat_completions_url,
                    headers=_headers(resolved),
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        detail = body.decode("utf-8", errors="ignore")[:400]
                        raise LLMRequestError(
                            f"LLM provider '{resolved.provider}' returned "
                            f"HTTP {response.status_code}: {detail}"
                        )

                    async for raw_line in response.aiter_lines():
                        line = raw_line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        token = delta.get("content")
                        if token:
                            yield str(token)
            except httpx.HTTPError as exc:
                raise LLMRequestError(
                    f"Could not reach LLM provider '{resolved.provider}': {exc}"
                ) from exc


# ─── Startup self-check ──────────────────────────────────────────────────────

async def check_llm_availability() -> bool:
    """
    Lightweight startup probe: verify the endpoint answers with the API key.

    Returns True when the provider is reachable and authorized. Never raises —
    a misconfigured key should surface as a log warning, not block boot.
    """
    try:
        reply = await chat_completion(
            [
                {"role": "system", "content": "Reply with the single word: ok"},
                {"role": "user", "content": "ping"},
            ],
            temperature=0.0,
            max_tokens=8,
            timeout=30.0,
        )
    except LLMConfigurationError as exc:
        logger.warning("[LLM] Not configured: %s", exc)
        return False
    except Exception as exc:
        logger.warning("[LLM] Startup probe failed: %s", exc)
        return False

    logger.info("[LLM] Provider reachable (probe reply: %r).", reply.strip()[:60])
    return True


def format_llm_error(exc: BaseException) -> str:
    """Render a user-facing markdown error block for chat/quiz responses."""
    try:
        resolved = resolve_llm_config()
        provider, model, base_url = resolved.provider, resolved.model, resolved.base_url
    except Exception:  # pragma: no cover - defensive
        provider, model, base_url = "?", "?", "?"

    if isinstance(exc, LLMConfigurationError):
        docs_url = (
            PROVIDER_PRESETS[provider].docs_url
            if provider in PROVIDER_PRESETS
            else "https://platform.deepseek.com/api_keys"
        )
        return (
            t("ai.error_config", docs_url=docs_url)
            + f"\n\n`provider={provider}` · `model={model}` · `base_url={base_url}`"
        )
    return (
        t("ai.error_request", message=str(exc))
        + f"\n\n`provider={provider}` · `model={model}` · `base_url={base_url}`"
    )
