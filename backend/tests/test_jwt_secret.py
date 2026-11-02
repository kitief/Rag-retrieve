"""Per-install JWT signing key (P0 task 3).

The security property under test is *not* "a key exists" — it is "two installs
never share a key, and the key survives a restart". A regression here is silent:
tokens keep working, so only a test can catch a return to a hard-coded default.
"""
import os
import stat
from pathlib import Path

import pytest

from app.config import (
    _INSECURE_JWT_SECRET,
    _MIN_JWT_SECRET_LENGTH,
    Settings,
    _read_jwt_secret_file,
    _write_jwt_secret_file,
    load_or_create_jwt_secret,
)


def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Detach the test from the developer's `.env` and shell."""
    for name in ("JWT_SECRET", "DATA_DIR", "DATABASE_URL", "CHROMA_PERSIST_DIR"):
        monkeypatch.delenv(name, raising=False)


def _settings(tmp_path: Path, **overrides) -> Settings:
    """Build Settings that ignores the repo `.env` file entirely."""
    return Settings(_env_file=None, data_dir=str(tmp_path), **overrides)


# ── The helper itself ────────────────────────────────────────────────────────


def test_first_run_generates_and_persists_a_key(tmp_path: Path) -> None:
    secret = load_or_create_jwt_secret(tmp_path)
    assert len(secret) >= _MIN_JWT_SECRET_LENGTH
    key_file = tmp_path / ".jwt_secret"
    assert key_file.is_file()
    assert key_file.read_text(encoding="utf-8").strip() == secret


def test_the_key_survives_a_restart(tmp_path: Path) -> None:
    first = load_or_create_jwt_secret(tmp_path)
    second = load_or_create_jwt_secret(tmp_path)
    assert first == second


def test_two_installs_never_share_a_key(tmp_path: Path) -> None:
    a = load_or_create_jwt_secret(tmp_path / "install-a")
    b = load_or_create_jwt_secret(tmp_path / "install-b")
    assert a != b


def test_a_truncated_key_file_is_replaced(tmp_path: Path) -> None:
    key_file = tmp_path / ".jwt_secret"
    key_file.write_text("too-short\n", encoding="utf-8")
    secret = load_or_create_jwt_secret(tmp_path)
    assert len(secret) >= _MIN_JWT_SECRET_LENGTH
    assert secret != "too-short"
    assert key_file.read_text(encoding="utf-8").strip() == secret


def test_a_blank_key_file_is_replaced(tmp_path: Path) -> None:
    (tmp_path / ".jwt_secret").write_text("   \n\n", encoding="utf-8")
    secret = load_or_create_jwt_secret(tmp_path)
    assert len(secret) >= _MIN_JWT_SECRET_LENGTH


def test_surrounding_whitespace_is_ignored(tmp_path: Path) -> None:
    (tmp_path / ".jwt_secret").write_text("  " + "k" * 40 + "\n", encoding="utf-8")
    assert load_or_create_jwt_secret(tmp_path) == "k" * 40


def test_the_key_file_is_not_world_readable(tmp_path: Path) -> None:
    """0o600 is honoured on POSIX; on Windows NTFS ACLs decide, so only assert
    where the mode is meaningful."""
    secret = "a" * 48
    _write_jwt_secret_file(tmp_path / ".jwt_secret", secret)
    if os.name == "posix":
        mode = stat.S_IMODE((tmp_path / ".jwt_secret").stat().st_mode)
        assert mode == 0o600


def test_an_unwritable_directory_returns_empty_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate the read-only case at the syscall, so the real error handling in
    ``_write_jwt_secret_file`` is what gets exercised."""

    def _deny(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(os, "open", _deny)
    assert load_or_create_jwt_secret(tmp_path) == ""


def test_unreadable_file_falls_back_to_generating(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".jwt_secret"
    path.write_text("x" * 48, encoding="utf-8")

    def _deny(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", _deny)
    assert _read_jwt_secret_file(path) == ""


# ── Wiring into Settings ────────────────────────────────────────────────────


def test_settings_without_a_configured_secret_generates_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    settings = _settings(tmp_path)
    assert settings.jwt_secret
    assert len(settings.jwt_secret) >= _MIN_JWT_SECRET_LENGTH
    assert (tmp_path / ".jwt_secret").is_file()
    # The key file and the live setting must agree, otherwise tokens minted
    # before a restart stop verifying after it.
    assert (tmp_path / ".jwt_secret").read_text(encoding="utf-8").strip() == settings.jwt_secret


def test_two_settings_objects_on_one_data_dir_reuse_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    assert _settings(tmp_path).jwt_secret == _settings(tmp_path).jwt_secret


def test_the_shipped_placeholder_is_treated_as_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An old `.env` may still carry the placeholder; it must not win."""
    _clean_env(monkeypatch)
    settings = _settings(tmp_path, jwt_secret=_INSECURE_JWT_SECRET)
    assert settings.jwt_secret != _INSECURE_JWT_SECRET
    assert (tmp_path / ".jwt_secret").is_file()


def test_an_explicit_secret_wins_and_is_not_written_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    explicit = "s" * 48
    settings = _settings(tmp_path, jwt_secret=explicit)
    assert settings.jwt_secret == explicit
    # Writing it would make the override permanent and surprising.
    assert not (tmp_path / ".jwt_secret").exists()


def test_a_short_explicit_secret_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    with pytest.raises(ValueError, match="at least 32 characters"):
        _settings(tmp_path, jwt_secret="short")


def test_a_read_only_data_dir_still_produces_a_working_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Starting must not be blocked by a bad data directory — but the key is
    ephemeral, which the config logs at error level."""
    _clean_env(monkeypatch)
    monkeypatch.setattr("app.config.load_or_create_jwt_secret", lambda root: "")
    settings = _settings(tmp_path)
    assert len(settings.jwt_secret) >= _MIN_JWT_SECRET_LENGTH


def test_generated_keys_differ_between_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_env(monkeypatch)
    a = _settings(tmp_path / "a").jwt_secret
    b = _settings(tmp_path / "b").jwt_secret
    assert a != b
