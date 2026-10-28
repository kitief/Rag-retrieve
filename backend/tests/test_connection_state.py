"""
Persistence of the "connected" badge in the API panel.

The panel used to keep the probe result in component state only, so closing and
reopening the dialog always showed "not connected" — even when the stored key was
answering questions perfectly well. These tests pin the server side of the fix:
the outcome of a probe is stored, returned by ``GET /settings``, and marked stale
whenever it no longer describes the configuration in use.
"""
import json

import pytest

from app.core import runtime_settings
from app.models.app_setting import AppSetting
from app.routers import settings as settings_router
from app.services import llm_client


@pytest.fixture(autouse=True)
def clean_overrides():
    """Keep the module-level override cache from leaking between tests."""
    runtime_settings.clear_overrides()
    yield
    runtime_settings.clear_overrides()


def _patch_models(monkeypatch, models=None, error: Exception | None = None):
    """Replace the endpoint probe with a canned answer."""
    calls: list[tuple[str, str]] = []

    async def fake_fetch(base_url: str, api_key: str, **_kwargs):
        calls.append((base_url, api_key))
        if error is not None:
            raise error
        return list(models or [])

    monkeypatch.setattr(llm_client, "fetch_models", fake_fetch)
    return calls


async def _seed_key(db_session, key: str = "sk-abcdefghijkl128e") -> None:
    """Store an active key so ``resolve_llm_config`` reports a usable config."""
    db_session.add(AppSetting(key="llm_api_key", value=key))
    db_session.add(AppSetting(key="llm_provider", value="deepseek"))
    db_session.add(AppSetting(key="llm_base_url", value="https://api.deepseek.com/v1"))
    db_session.add(AppSetting(key="llm_model", value="deepseek-flash"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_connect_result_is_returned_by_get_settings(
    client, auth_headers, db_session, monkeypatch
):
    """A successful probe must still be visible after the dialog is reopened."""
    _patch_models(monkeypatch, models=["deepseek-flash", "deepseek-v4-pro"])

    # The real sequence: save the key first, then probe without retyping it.
    await client.put(
        "/settings",
        json={
            "llm_provider": "deepseek",
            "llm_base_url": "https://api.deepseek.com/v1",
            "llm_api_key": "sk-abcdefghijkl128e",
        },
        headers=auth_headers,
    )

    connect = await client.post(
        "/settings/llm/connect",
        json={"llm_provider": "deepseek", "llm_base_url": "https://api.deepseek.com/v1"},
        headers=auth_headers,
    )
    assert connect.status_code == 200
    assert connect.json()["ok"] is True

    # A fresh GET is what the dialog does on every open.
    reread = await client.get("/settings", headers=auth_headers)
    assert reread.status_code == 200
    connection = reread.json()["llm"]["connection"]
    assert connection is not None, "the probe result was not persisted"
    assert connection["ok"] is True
    assert connection["stale"] is False
    assert connection["models"] == ["deepseek-flash", "deepseek-v4-pro"]
    assert connection["base_url"] == "https://api.deepseek.com/v1"
    assert connection["checked_at"]


@pytest.mark.asyncio
async def test_connection_never_stores_the_raw_key(client, auth_headers, db_session, monkeypatch):
    """Only a masked hint may be persisted; the secret stays in the vault."""
    _patch_models(monkeypatch, models=["deepseek-flash"])
    secret = "sk-abcdefghijkl128e"

    await client.put("/settings", json={"llm_api_key": secret}, headers=auth_headers)
    await client.post(
        "/settings/llm/connect",
        json={"llm_provider": "deepseek"},
        headers=auth_headers,
    )

    row = await db_session.get(AppSetting, "llm_connection")
    assert row is not None
    assert secret not in row.value
    assert json.loads(row.value)["key_hint"].endswith("128e")


@pytest.mark.asyncio
async def test_probe_becomes_stale_when_the_base_url_changes(
    client, auth_headers, db_session, monkeypatch
):
    """A green badge must not outlive the endpoint it was measured against."""
    _patch_models(monkeypatch, models=["deepseek-flash"])
    await client.put(
        "/settings",
        json={"llm_provider": "deepseek", "llm_api_key": "sk-abcdefghijkl128e"},
        headers=auth_headers,
    )
    await client.post("/settings/llm/connect", json={"llm_provider": "deepseek"}, headers=auth_headers)

    await client.put(
        "/settings",
        json={"llm_base_url": "https://other.example.com/v1"},
        headers=auth_headers,
    )

    connection = (await client.get("/settings", headers=auth_headers)).json()["llm"]["connection"]
    assert connection is not None
    assert connection["stale"] is True, "a stale probe must not read as connected"


@pytest.mark.asyncio
async def test_probe_becomes_stale_when_the_key_changes(
    client, auth_headers, db_session, monkeypatch
):
    """Swapping the secret invalidates the previous probe."""
    _patch_models(monkeypatch, models=["deepseek-flash"])
    await client.put(
        "/settings",
        json={"llm_provider": "deepseek", "llm_api_key": "sk-abcdefghijkl128e"},
        headers=auth_headers,
    )
    await client.post("/settings/llm/connect", json={"llm_provider": "deepseek"}, headers=auth_headers)

    await client.put(
        "/settings",
        json={"llm_api_key": "sk-zzzzzzzzzzzz9999"},
        headers=auth_headers,
    )

    connection = (await client.get("/settings", headers=auth_headers)).json()["llm"]["connection"]
    assert connection is not None
    assert connection["stale"] is True


@pytest.mark.asyncio
async def test_failed_probe_is_stored_as_not_connected(
    client, auth_headers, db_session, monkeypatch
):
    """A rejection is worth remembering too: it explains the red badge."""
    _patch_models(
        monkeypatch,
        error=llm_client.LLMRequestError("HTTP 401 unauthorized"),
    )

    await client.put(
        "/settings",
        json={"llm_provider": "deepseek", "llm_api_key": "sk-bogus0000000000"},
        headers=auth_headers,
    )
    response = await client.post(
        "/settings/llm/connect",
        json={"llm_provider": "deepseek"},
        headers=auth_headers,
    )
    assert response.json()["ok"] is False

    connection = (await client.get("/settings", headers=auth_headers)).json()["llm"]["connection"]
    assert connection is not None
    assert connection["ok"] is False
    assert "401" in connection["message"]


@pytest.mark.asyncio
async def test_reset_settings_clears_the_remembered_connection(
    client, auth_headers, db_session, monkeypatch
):
    """Restoring defaults must not leave a badge behind."""
    _patch_models(monkeypatch, models=["deepseek-flash"])
    await client.put(
        "/settings",
        json={"llm_provider": "deepseek", "llm_api_key": "sk-abcdefghijkl128e"},
        headers=auth_headers,
    )
    await client.post("/settings/llm/connect", json={"llm_provider": "deepseek"}, headers=auth_headers)

    await client.delete("/settings", headers=auth_headers)

    assert (await client.get("/settings", headers=auth_headers)).json()["llm"]["connection"] is None


@pytest.mark.asyncio
async def test_corrupt_stored_state_does_not_break_the_panel(
    client, auth_headers, db_session, monkeypatch
):
    """A damaged row degrades to "no connection", never to a 500."""
    _patch_models(monkeypatch, models=["deepseek-flash"])
    await _seed_key(db_session)
    db_session.add(AppSetting(key="llm_connection", value="{not json"))
    await db_session.commit()

    response = await client.get("/settings", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["llm"]["connection"] is None


@pytest.mark.asyncio
async def test_no_connection_block_when_nothing_was_ever_probed(client, auth_headers, db_session):
    """Fresh install: the field is simply absent, so the UI shows red."""
    await _seed_key(db_session)
    connection = (await client.get("/settings", headers=auth_headers)).json()["llm"]["connection"]
    assert connection is None
