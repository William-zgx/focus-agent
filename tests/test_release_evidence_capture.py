from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import release_evidence_capture

CAPTURED_AT = datetime(2026, 7, 12, 9, 30, 45, tzinfo=UTC)
CAPTURED_AT_TEXT = "2026-07-12T09:30:45Z"
RELEASE_ENV = {
    "RELEASE_COMMIT_SHA": "0123456789abcdef0123456789abcdef01234567",
    "RELEASE_DEPLOYMENT_ID": "focus-agent-prod-20260712",
    "RELEASE_DEPLOYMENT_VERSION": "1.4.0",
    "RELEASE_ENVIRONMENT": "production",
}
EXPECTED_BINDING = {
    "commit_sha": RELEASE_ENV["RELEASE_COMMIT_SHA"],
    "deployment_id": RELEASE_ENV["RELEASE_DEPLOYMENT_ID"],
    "deployment_version": RELEASE_ENV["RELEASE_DEPLOYMENT_VERSION"],
    "environment": RELEASE_ENV["RELEASE_ENVIRONMENT"],
}


@pytest.fixture(autouse=True)
def _fixed_capture_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release_evidence_capture, "_capture_time", lambda: CAPTURED_AT)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_capture_in_place_preserves_timestamp_and_canonicalizes_matching_bindings(
    tmp_path: Path,
) -> None:
    source = _write_json(
        tmp_path / "report.json",
        {
            "generated_at": "2026-07-12T08:00:00+08:00",
            "meta": {
                "release_binding": {**EXPECTED_BINDING, "environment": "prod"},
                "source": "trusted-command",
            },
            "release_binding": EXPECTED_BINDING,
            "status": "passed",
        },
    )

    written = release_evidence_capture.capture_json_files(
        [source],
        in_place=True,
        env=RELEASE_ENV,
    )

    assert written == [source]
    assert _load_json(source) == {
        "generated_at": "2026-07-12T08:00:00+08:00",
        "meta": {"source": "trusted-command"},
        "release_binding": EXPECTED_BINDING,
        "status": "passed",
    }


@pytest.mark.parametrize("location", ("top-level", "meta"))
@pytest.mark.parametrize(
    ("existing_binding", "message"),
    (
        (
            {
                "commit_sha": EXPECTED_BINDING["commit_sha"],
                "deployment_id": EXPECTED_BINDING["deployment_id"],
                "deployment_version": EXPECTED_BINDING["deployment_version"],
            },
            "environment is missing",
        ),
        (
            {**EXPECTED_BINDING, "deployment_version": "forged-version"},
            "deployment_version does not match",
        ),
    ),
)
def test_capture_rejects_partial_or_mismatched_existing_binding_without_writing(
    location: str,
    existing_binding: dict[str, str],
    message: str,
    tmp_path: Path,
) -> None:
    payload: dict[str, object] = {
        "generated_at": "2026-07-12T08:00:00Z",
        "status": "passed",
    }
    if location == "top-level":
        payload["release_binding"] = existing_binding
    else:
        payload["meta"] = {"release_binding": existing_binding}
    source = _write_json(tmp_path / "report.json", payload)
    original = source.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match=message,
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert source.read_bytes() == original


def test_capture_rejects_conflicting_top_level_and_meta_bindings_without_writing(
    tmp_path: Path,
) -> None:
    source = _write_json(
        tmp_path / "report.json",
        {
            "generated_at": "2026-07-12T08:00:00Z",
            "meta": {
                "release_binding": {
                    **EXPECTED_BINDING,
                    "deployment_id": "forged-deployment",
                }
            },
            "release_binding": EXPECTED_BINDING,
            "status": "passed",
        },
    )
    original = source.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="meta.release_binding deployment_id does not match",
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert source.read_bytes() == original


@pytest.mark.parametrize(
    ("timestamp_path", "timestamp"),
    (
        (("generated_at",), "2026-07-10T01:02:03Z"),
        (("meta", "generated_at"), "2026-07-10T09:02:03+08:00"),
        (("checked_at",), "2026-07-10T01:02:03+00:00"),
        (("completed_at",), "2026-07-10T01:02:04Z"),
        (("finished_at",), "2026-07-10T01:02:05Z"),
        (("timestamp",), "2026-07-10T01:02:06Z"),
    ),
)
def test_capture_promotes_existing_schema_v2_timestamp_without_laundering(
    timestamp_path: tuple[str, ...],
    timestamp: str,
    tmp_path: Path,
) -> None:
    payload: dict[str, object] = {"status": "passed"}
    current = payload
    for segment in timestamp_path[:-1]:
        nested: dict[str, object] = {}
        current[segment] = nested
        current = nested
    current[timestamp_path[-1]] = timestamp
    source = _write_json(tmp_path / "report.json", payload)

    release_evidence_capture.capture_json_files(
        [source],
        in_place=True,
        env=RELEASE_ENV,
    )

    captured = _load_json(source)
    assert isinstance(captured, dict)
    assert captured["generated_at"] == timestamp
    assert captured["generated_at"] != CAPTURED_AT_TEXT


def test_captured_now_preserves_existing_stale_timestamp(tmp_path: Path) -> None:
    stale_timestamp = "2025-01-01T00:00:00Z"
    source = _write_json(
        tmp_path / "report.json",
        {"generated_at": stale_timestamp, "status": "passed"},
    )

    release_evidence_capture.capture_json_files(
        [source],
        in_place=True,
        captured_now=True,
        env=RELEASE_ENV,
    )

    captured = _load_json(source)
    assert isinstance(captured, dict)
    assert captured["generated_at"] == stale_timestamp


def test_capture_rejects_missing_timestamp_by_default(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "report.json", {"status": "passed"})
    original = source.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="accepted evidence timestamp",
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert source.read_bytes() == original


def test_capture_uses_capture_time_only_with_explicit_opt_in(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "report.json", {"status": "passed"})

    release_evidence_capture.capture_json_files(
        [source],
        in_place=True,
        captured_now=True,
        env=RELEASE_ENV,
    )

    captured = _load_json(source)
    assert isinstance(captured, dict)
    assert captured["generated_at"] == CAPTURED_AT_TEXT


@pytest.mark.parametrize("missing_name", tuple(RELEASE_ENV))
def test_capture_fails_closed_when_any_release_identity_field_is_missing(
    missing_name: str,
    tmp_path: Path,
) -> None:
    source = _write_json(
        tmp_path / "report.json",
        {"generated_at": "2026-07-12T08:00:00Z", "status": "passed"},
    )
    original = source.read_bytes()
    partial_env = {key: value for key, value in RELEASE_ENV.items() if key != missing_name}

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match=missing_name,
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            env=partial_env,
        )

    assert source.read_bytes() == original
    assert list(tmp_path.glob(".*.tmp")) == []


def test_capture_fails_closed_when_all_release_identity_fields_are_missing(
    tmp_path: Path,
) -> None:
    source = _write_json(
        tmp_path / "report.json",
        {"generated_at": "2026-07-12T08:00:00Z", "status": "passed"},
    )
    original = source.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="RELEASE_COMMIT_SHA",
    ):
        release_evidence_capture.capture_json_files([source], in_place=True, env={})

    assert source.read_bytes() == original


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (["not", "an", "object"], "top-level JSON object"),
        ({"generated_at": "2026-07-12T09:00:00"}, "include a timezone"),
        (
            {"meta": {"generated_at": "2026-07-12T09:00:00"}},
            "meta.generated_at must include a timezone",
        ),
        ({"generated_at": "not-a-timestamp"}, "valid ISO-8601"),
    ),
)
def test_capture_rejects_invalid_payload_without_replacing_existing_target(
    payload: object,
    message: str,
    tmp_path: Path,
) -> None:
    source = _write_json(tmp_path / "source.json", payload)
    target = _write_json(tmp_path / "target.json", {"keep": "existing"})
    original_target = target.read_bytes()

    with pytest.raises(release_evidence_capture.ReleaseEvidenceCaptureError, match=message):
        release_evidence_capture.capture_json_files(
            [source],
            output_path=target,
            env=RELEASE_ENV,
        )

    assert target.read_bytes() == original_target


def test_captured_now_does_not_override_invalid_existing_timestamp(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "source.json",
        {"generated_at": "2026-07-12T09:00:00", "status": "passed"},
    )
    original = source.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="include a timezone",
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            captured_now=True,
            env=RELEASE_ENV,
        )

    assert source.read_bytes() == original


def test_capture_reports_missing_and_invalid_json_paths_without_writing(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    target = tmp_path / "target.json"

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="does not exist",
    ):
        release_evidence_capture.capture_json_files(
            [missing],
            output_path=target,
            env=RELEASE_ENV,
        )
    assert not target.exists()

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="invalid JSON",
    ):
        release_evidence_capture.capture_json_files(
            [invalid],
            output_path=target,
            env=RELEASE_ENV,
        )
    assert not target.exists()


def test_capture_auto_validates_readyz_identity_from_filename_and_content(
    tmp_path: Path,
) -> None:
    readyz = _write_json(
        tmp_path / "readyz.json",
        {
            "app_version": RELEASE_ENV["RELEASE_DEPLOYMENT_VERSION"],
            "deployment": RELEASE_ENV["RELEASE_DEPLOYMENT_ID"],
            "environment": "prod",
            "generated_at": "2026-07-12T08:00:00Z",
            "ready": True,
            "status": "ok",
        },
    )

    release_evidence_capture.capture_json_files(
        [readyz],
        in_place=True,
        env={**RELEASE_ENV, "RELEASE_ENVIRONMENT": "prod"},
    )

    payload = _load_json(readyz)
    assert isinstance(payload, dict)
    assert payload["release_binding"]["environment"] == "production"
    assert payload["generated_at"] == "2026-07-12T08:00:00Z"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("deployment", "wrong-deployment", "readyz deployment"),
        ("app_version", "wrong-version", "readyz app_version"),
        ("environment", "staging", "readyz environment"),
    ),
)
def test_capture_rejects_readyz_identity_mismatch_without_writing(
    field: str,
    value: str,
    message: str,
    tmp_path: Path,
) -> None:
    payload = {
        "app_version": RELEASE_ENV["RELEASE_DEPLOYMENT_VERSION"],
        "deployment": RELEASE_ENV["RELEASE_DEPLOYMENT_ID"],
        "environment": RELEASE_ENV["RELEASE_ENVIRONMENT"],
        "generated_at": "2026-07-12T08:00:00Z",
        "ready": True,
    }
    payload[field] = value
    readyz = _write_json(tmp_path / "readyz.json", payload)
    original = readyz.read_bytes()

    with pytest.raises(release_evidence_capture.ReleaseEvidenceCaptureError, match=message):
        release_evidence_capture.capture_json_files(
            [readyz],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert readyz.read_bytes() == original


def test_capture_explicit_readyz_requires_all_runtime_identity_fields(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "runtime.json",
        {
            "generated_at": "2026-07-12T08:00:00Z",
            "ready": True,
            "status": "ok",
        },
    )

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="readyz deployment is missing",
    ):
        release_evidence_capture.capture_json_files(
            [source],
            in_place=True,
            readyz_paths=[source],
            env=RELEASE_ENV,
        )


def test_capture_validates_every_input_before_writing_any_output(tmp_path: Path) -> None:
    first = _write_json(tmp_path / "first.json", {"status": "passed"})
    second = _write_json(
        tmp_path / "second.json",
        {"generated_at": "2026-07-12T09:00:00", "status": "passed"},
    )
    first_original = first.read_bytes()
    second_original = second.read_bytes()

    with pytest.raises(release_evidence_capture.ReleaseEvidenceCaptureError):
        release_evidence_capture.capture_json_files(
            [first, second],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert first.read_bytes() == first_original
    assert second.read_bytes() == second_original


def test_capture_batch_does_not_launder_stale_time_or_partially_write(
    tmp_path: Path,
) -> None:
    stale_timestamp = "2025-01-01T00:00:00Z"
    first = _write_json(
        tmp_path / "first.json",
        {"generated_at": stale_timestamp, "status": "passed"},
    )
    invalid_readyz = _write_json(
        tmp_path / "readyz.json",
        {
            "app_version": "wrong-version",
            "deployment": RELEASE_ENV["RELEASE_DEPLOYMENT_ID"],
            "environment": RELEASE_ENV["RELEASE_ENVIRONMENT"],
            "generated_at": "2026-07-12T08:00:00Z",
            "ready": True,
        },
    )
    first_original = first.read_bytes()
    readyz_original = invalid_readyz.read_bytes()

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="readyz app_version",
    ):
        release_evidence_capture.capture_json_files(
            [first, invalid_readyz],
            in_place=True,
            env=RELEASE_ENV,
        )

    assert first.read_bytes() == first_original
    assert invalid_readyz.read_bytes() == readyz_original
    assert json.loads(first_original)["generated_at"] == stale_timestamp


def test_capture_multiple_files_to_output_directory_uses_one_capture_time(
    tmp_path: Path,
) -> None:
    first = _write_json(tmp_path / "source" / "first.json", {"value": 1})
    second = _write_json(tmp_path / "source" / "second.json", {"value": 2})
    output_dir = tmp_path / "captured"

    written = release_evidence_capture.capture_json_files(
        [first, second],
        output_dir=output_dir,
        captured_now=True,
        env=RELEASE_ENV,
    )

    assert written == [output_dir / "first.json", output_dir / "second.json"]
    assert {_load_json(path)["generated_at"] for path in written} == {CAPTURED_AT_TEXT}
    assert all(_load_json(path)["release_binding"] == EXPECTED_BINDING for path in written)
    assert _load_json(first) == {"value": 1}
    assert _load_json(second) == {"value": 2}


def test_capture_rejects_output_name_collisions_before_writing(tmp_path: Path) -> None:
    first = _write_json(
        tmp_path / "a" / "report.json",
        {"generated_at": "2026-07-12T08:00:00Z", "value": 1},
    )
    second = _write_json(
        tmp_path / "b" / "report.json",
        {"generated_at": "2026-07-12T08:00:00Z", "value": 2},
    )
    output_dir = tmp_path / "captured"

    with pytest.raises(
        release_evidence_capture.ReleaseEvidenceCaptureError,
        match="same output path",
    ):
        release_evidence_capture.capture_json_files(
            [first, second],
            output_dir=output_dir,
            env=RELEASE_ENV,
        )

    assert not output_dir.exists()


def test_capture_commits_each_valid_json_with_atomic_replace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _write_json(
        tmp_path / "source.json",
        {"generated_at": "2026-07-12T08:00:00Z", "status": "passed"},
    )
    target = tmp_path / "nested" / "target.json"
    real_replace = os.replace
    replacements: list[tuple[Path, Path]] = []

    def recording_replace(source_path: str | os.PathLike[str], target_path: str | os.PathLike[str]):
        replacements.append((Path(source_path), Path(target_path)))
        return real_replace(source_path, target_path)

    monkeypatch.setattr(release_evidence_capture.os, "replace", recording_replace)

    release_evidence_capture.capture_json_files(
        [source],
        output_path=target,
        env=RELEASE_ENV,
    )

    assert len(replacements) == 1
    temporary_path, replaced_target = replacements[0]
    assert temporary_path.parent == target.parent
    assert temporary_path != target
    assert replaced_target == target
    assert not temporary_path.exists()


def test_cli_captures_one_file_to_explicit_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in RELEASE_ENV.items():
        monkeypatch.setenv(name, value)
    source = _write_json(tmp_path / "source.json", {"status": "passed"})
    target = tmp_path / "target.json"

    exit_code = release_evidence_capture.main(
        [str(source), "--output", str(target), "--captured-now"]
    )

    assert exit_code == 0
    assert _load_json(target) == {
        "generated_at": CAPTURED_AT_TEXT,
        "release_binding": EXPECTED_BINDING,
        "status": "passed",
    }
    stdout = json.loads(capsys.readouterr().out)
    assert stdout == {"captured": [str(target)], "count": 1, "status": "passed"}


def test_cli_rejects_timestamp_free_static_report_without_captured_now(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name, value in RELEASE_ENV.items():
        monkeypatch.setenv(name, value)
    source = _write_json(tmp_path / "source.json", {"status": "passed"})
    target = tmp_path / "target.json"

    exit_code = release_evidence_capture.main([str(source), "--output", str(target)])

    assert exit_code == 2
    assert not target.exists()
    stderr = json.loads(capsys.readouterr().err)
    assert stderr["status"] == "failed"
    assert "accepted evidence timestamp" in stderr["error"]
