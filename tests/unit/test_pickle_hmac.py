from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pytest

from focus_agent.engine import local_persistence

_HMAC_KEY_ENV = "FOCUS_AGENT_CHECKPOINT_HMAC_KEY"
_VERIFY_SIGNATURE_ENV = "FOCUS_AGENT_CHECKPOINT_VERIFY_SIGNATURE"
_HMAC_KEY = "checkpoint-hmac-key-32-characters"


def _write_unsigned_pickle(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)


def test_pickle_load_accepts_valid_hmac_signature(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(_HMAC_KEY_ENV, _HMAC_KEY)
    monkeypatch.delenv(_VERIFY_SIGNATURE_ENV, raising=False)
    path = tmp_path / "checkpoint.pkl"
    payload = {"storage": {"thread-1": {"": {"checkpoint": "ok"}}}}

    local_persistence._atomic_pickle_dump(path, payload)

    assert local_persistence._checkpoint_signature_path(path).is_file()
    assert local_persistence._pickle_load(path) == payload


def test_pickle_load_rejects_missing_signature_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_HMAC_KEY_ENV, _HMAC_KEY)
    monkeypatch.delenv(_VERIFY_SIGNATURE_ENV, raising=False)
    path = tmp_path / "checkpoint.pkl"
    _write_unsigned_pickle(path, {"ok": True})

    caplog.set_level(logging.WARNING, logger="focus_agent.local_persistence")

    assert local_persistence._pickle_load(path) is None
    assert "without signature" in caplog.text


def test_pickle_load_rejects_when_verification_enabled_without_hmac_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(_HMAC_KEY_ENV, raising=False)
    monkeypatch.delenv(_VERIFY_SIGNATURE_ENV, raising=False)
    path = tmp_path / "checkpoint.pkl"
    _write_unsigned_pickle(path, {"ok": True})

    caplog.set_level(logging.WARNING, logger="focus_agent.local_persistence")

    assert local_persistence._pickle_load(path) is None
    assert _HMAC_KEY_ENV in caplog.text or "without signature" in caplog.text


def test_pickle_load_rejects_bad_signature(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_HMAC_KEY_ENV, _HMAC_KEY)
    monkeypatch.delenv(_VERIFY_SIGNATURE_ENV, raising=False)
    path = tmp_path / "checkpoint.pkl"
    local_persistence._atomic_pickle_dump(path, {"ok": True})
    local_persistence._checkpoint_signature_path(path).write_text("bad-signature\n", encoding="utf-8")

    caplog.set_level(logging.WARNING, logger="focus_agent.local_persistence")

    assert local_persistence._pickle_load(path) is None
    assert "invalid signature" in caplog.text


def test_pickle_load_allows_unsigned_file_when_signature_verification_is_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv(_HMAC_KEY_ENV, raising=False)
    monkeypatch.setenv(_VERIFY_SIGNATURE_ENV, "false")
    path = tmp_path / "checkpoint.pkl"
    payload = {"legacy": True}
    _write_unsigned_pickle(path, payload)

    assert local_persistence._pickle_load(path) == payload


def test_pickle_load_rejects_owner_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(_HMAC_KEY_ENV, _HMAC_KEY)
    monkeypatch.delenv(_VERIFY_SIGNATURE_ENV, raising=False)
    path = tmp_path / "checkpoint.pkl"
    local_persistence._atomic_pickle_dump(path, {"ok": True})

    def owner_matches(checked_path: Path) -> bool:
        return checked_path != path

    monkeypatch.setattr(local_persistence, "_checkpoint_file_owner_matches", owner_matches)
    caplog.set_level(logging.WARNING, logger="focus_agent.local_persistence")

    assert local_persistence._pickle_load(path) is None
    assert "owner mismatch" in caplog.text
