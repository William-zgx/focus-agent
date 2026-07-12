from __future__ import annotations

from pathlib import Path

import pytest

from focus_agent.config import Settings
from focus_agent.engine import local_persistence
from focus_agent.engine.local_persistence import (
    PersistentInMemorySaver,
    PersistentInMemoryStore,
)
from focus_agent.engine.runtime_persistence import _create_local_fallback_persistence

_HMAC_KEY = "fail-closed-persistence-test-key-32-chars"
_PERSISTENCE_CASES = (
    (
        PersistentInMemorySaver,
        {"storage": {}, "writes": {}, "blobs": {}},
    ),
    (
        PersistentInMemoryStore,
        {"data": {}, "vectors": {}},
    ),
)


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_missing_pickle_starts_empty_without_creating_a_file(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    del payload
    path = tmp_path / "missing.pkl"

    persistence = persistence_class(path, hmac_key=_HMAC_KEY)
    persistence.close()

    assert not path.exists()
    assert not local_persistence._checkpoint_signature_path(path).exists()


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_valid_signed_pickle_loads_normally(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    path = tmp_path / "valid.pkl"
    local_persistence._atomic_pickle_dump(path, payload, hmac_key=_HMAC_KEY)

    persistence = persistence_class(path, hmac_key=_HMAC_KEY)
    persistence.close()

    assert path.exists()
    assert local_persistence._checkpoint_signature_path(path).exists()


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_existing_pickle_without_signature_fails_closed_without_overwrite(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    path = tmp_path / "unsigned.pkl"
    data = local_persistence.pickle.dumps(
        payload,
        protocol=local_persistence.pickle.HIGHEST_PROTOCOL,
    )
    path.write_bytes(data)

    with pytest.raises(ValueError, match="missing HMAC signature"):
        persistence_class(path, hmac_key=_HMAC_KEY)

    assert path.read_bytes() == data
    assert not local_persistence._checkpoint_signature_path(path).exists()


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_existing_pickle_with_tampered_signature_fails_closed_without_overwrite(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    path = tmp_path / "tampered.pkl"
    local_persistence._atomic_pickle_dump(path, payload, hmac_key=_HMAC_KEY)
    signature_path = local_persistence._checkpoint_signature_path(path)
    signature_path.write_text("tampered-signature\n", encoding="utf-8")
    original_data = path.read_bytes()

    with pytest.raises(ValueError, match="invalid HMAC signature"):
        persistence_class(path, hmac_key=_HMAC_KEY)

    assert path.read_bytes() == original_data
    assert signature_path.read_text(encoding="utf-8") == "tampered-signature\n"


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_existing_signed_pickle_without_hmac_key_fails_closed_without_overwrite(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    path = tmp_path / "missing-key.pkl"
    local_persistence._atomic_pickle_dump(path, payload, hmac_key=_HMAC_KEY)
    signature_path = local_persistence._checkpoint_signature_path(path)
    original_data = path.read_bytes()
    original_signature = signature_path.read_bytes()

    with pytest.raises(ValueError, match="FOCUS_AGENT_CHECKPOINT_HMAC_KEY"):
        persistence_class(path)

    assert path.read_bytes() == original_data
    assert signature_path.read_bytes() == original_signature


@pytest.mark.parametrize(
    ("persistence_class", "payload", "mismatched_file"),
    (
        *(
            (persistence_class, payload, "pickle")
            for persistence_class, payload in _PERSISTENCE_CASES
        ),
        *(
            (persistence_class, payload, "signature")
            for persistence_class, payload in _PERSISTENCE_CASES
        ),
    ),
    ids=("saver-pickle", "store-pickle", "saver-signature", "store-signature"),
)
def test_existing_pickle_with_owner_mismatch_fails_closed_without_overwrite(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    mismatched_file: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "owner-mismatch.pkl"
    local_persistence._atomic_pickle_dump(path, payload, hmac_key=_HMAC_KEY)
    signature_path = local_persistence._checkpoint_signature_path(path)
    original_data = path.read_bytes()
    original_signature = signature_path.read_bytes()
    rejected_path = path if mismatched_file == "pickle" else signature_path

    monkeypatch.setattr(
        local_persistence,
        "_checkpoint_file_owner_matches",
        lambda candidate: candidate != rejected_path,
    )

    with pytest.raises(ValueError, match="owner mismatch"):
        persistence_class(path, hmac_key=_HMAC_KEY)

    assert path.read_bytes() == original_data
    assert signature_path.read_bytes() == original_signature


@pytest.mark.parametrize(
    ("persistence_class", "payload"),
    _PERSISTENCE_CASES,
    ids=("saver", "store"),
)
def test_existing_signed_but_corrupt_pickle_fails_closed_without_overwrite(
    persistence_class: type[PersistentInMemorySaver] | type[PersistentInMemoryStore],
    payload: dict[str, object],
    tmp_path: Path,
) -> None:
    del payload
    path = tmp_path / "corrupt.pkl"
    corrupt_data = b"not-a-valid-pickle"
    path.write_bytes(corrupt_data)
    signature = local_persistence._checkpoint_hmac_digest(
        corrupt_data,
        _HMAC_KEY.encode("utf-8"),
    )
    signature_path = local_persistence._checkpoint_signature_path(path)
    signature_path.write_text(signature + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="corrupt or incompatible"):
        persistence_class(path, hmac_key=_HMAC_KEY)

    assert path.read_bytes() == corrupt_data
    assert signature_path.read_text(encoding="utf-8") == signature + "\n"


@pytest.mark.parametrize(
    ("explicit_backend", "file_name"),
    (
        (True, "langgraph-checkpoints.pkl"),
        (True, "langgraph-store.pkl"),
        (False, "langgraph-checkpoints.pkl"),
        (False, "langgraph-store.pkl"),
    ),
    ids=(
        "explicit-pickle-saver",
        "explicit-pickle-store",
        "selected-legacy-pickle-saver",
        "selected-legacy-pickle-store",
    ),
)
def test_runtime_pickle_selection_rejects_signed_corrupt_file_without_overwrite(
    explicit_backend: bool,
    file_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("FOCUS_AGENT_CHECKPOINT_HMAC_KEY", raising=False)
    corrupt_path = tmp_path / file_name
    corrupt_data = b"signed-but-corrupt-pickle"
    corrupt_path.write_bytes(corrupt_data)
    signature = local_persistence._checkpoint_hmac_digest(
        corrupt_data,
        _HMAC_KEY.encode("utf-8"),
    )
    signature_path = local_persistence._checkpoint_signature_path(corrupt_path)
    signature_path.write_text(signature + "\n", encoding="utf-8")
    resolved_env = {"FOCUS_AGENT_CHECKPOINT_HMAC_KEY": _HMAC_KEY}
    if explicit_backend:
        resolved_env["FOCUS_AGENT_CHECKPOINT_BACKEND"] = "pickle"
    settings = Settings(
        branch_db_path=str(tmp_path / "branches.sqlite3"),
        resolved_env=resolved_env,
    )

    with pytest.raises(ValueError, match="corrupt or incompatible"):
        _create_local_fallback_persistence(settings)

    assert corrupt_path.read_bytes() == corrupt_data
    assert signature_path.read_text(encoding="utf-8") == signature + "\n"
    assert not (tmp_path / "langgraph-checkpoints.sqlite3").exists()
    assert not (tmp_path / "langgraph-store.sqlite3").exists()
