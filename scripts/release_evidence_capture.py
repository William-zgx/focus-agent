#!/usr/bin/env python3
"""Attach trusted release identity to raw JSON evidence without laundering freshness."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.release_identity import RELEASE_IDENTITY_ENV  # noqa: E402

_TIMESTAMP_PATHS = (
    ("generated_at",),
    ("meta", "generated_at"),
    ("checked_at",),
    ("completed_at",),
    ("finished_at",),
    ("timestamp",),
)
_BINDING_FIELDS = (
    "commit_sha",
    "deployment_id",
    "deployment_version",
    "environment",
)
_READYZ_FIELDS = {
    "deployment": "deployment_id",
    "app_version": "deployment_version",
    "environment": "environment",
}


class ReleaseEvidenceCaptureError(ValueError):
    """Raised when raw release evidence cannot be safely attested."""


def _capture_time() -> datetime:
    return datetime.now(UTC)


def _format_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ReleaseEvidenceCaptureError("capture time must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _non_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_environment(value: str) -> str:
    normalized = value.strip().lower()
    return "production" if normalized == "prod" else normalized


def _release_binding(env: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for field, env_name in RELEASE_IDENTITY_ENV.items():
        value = _non_empty(env.get(env_name))
        if value is None:
            missing.append(env_name)
            continue
        values[field] = _canonical_environment(value) if field == "environment" else value
    if missing:
        raise ReleaseEvidenceCaptureError(
            "trusted release capture requires complete release identity; missing environment "
            "variables: " + ", ".join(missing)
        )
    return values


def _nested_value(payload: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _timestamp_label(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _validate_timestamp(value: Any, *, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseEvidenceCaptureError(f"{source} must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ReleaseEvidenceCaptureError(f"{source} must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseEvidenceCaptureError(f"{source} must include a timezone")
    return value


def _evidence_timestamp(
    payload: Mapping[str, Any],
    *,
    captured_at: datetime,
    captured_now: bool,
) -> str:
    selected: str | None = None
    for path in _TIMESTAMP_PATHS:
        value = _nested_value(payload, path)
        if value is None:
            continue
        validated = _validate_timestamp(value, source=_timestamp_label(path))
        if selected is None:
            selected = validated
    if selected is not None:
        return selected
    if captured_now:
        return _format_utc(captured_at)
    accepted = ", ".join(_timestamp_label(path) for path in _TIMESTAMP_PATHS)
    raise ReleaseEvidenceCaptureError(
        "evidence must declare an accepted evidence timestamp; expected one of: " + accepted
    )


def _validate_existing_binding(
    binding: Any,
    *,
    expected: Mapping[str, str],
    source: str,
) -> None:
    if not isinstance(binding, Mapping):
        raise ReleaseEvidenceCaptureError(f"{source} must be a JSON object")
    for field in _BINDING_FIELDS:
        actual = _non_empty(binding.get(field))
        if actual is None:
            raise ReleaseEvidenceCaptureError(f"{source} {field} is missing")
        if field == "environment":
            actual = _canonical_environment(actual)
        if actual != expected[field]:
            raise ReleaseEvidenceCaptureError(
                f"{source} {field} does not match the trusted release identity "
                f"(expected {expected[field]!r}, got {actual!r})"
            )


def _validate_declared_bindings(
    payload: Mapping[str, Any],
    *,
    expected: Mapping[str, str],
) -> None:
    if "release_binding" in payload:
        _validate_existing_binding(
            payload["release_binding"],
            expected=expected,
            source="release_binding",
        )
    meta = payload.get("meta")
    if isinstance(meta, Mapping) and "release_binding" in meta:
        _validate_existing_binding(
            meta["release_binding"],
            expected=expected,
            source="meta.release_binding",
        )


def _looks_like_readyz(path: Path, payload: Mapping[str, Any]) -> bool:
    if path.stem.lower() == "readyz":
        return True
    return "ready" in payload and any(field in payload for field in _READYZ_FIELDS)


def _validate_readyz(payload: Mapping[str, Any], *, expected: Mapping[str, str]) -> None:
    for payload_field, binding_field in _READYZ_FIELDS.items():
        actual = _non_empty(payload.get(payload_field))
        if actual is None:
            raise ReleaseEvidenceCaptureError(f"readyz {payload_field} is missing")
        if payload_field == "environment":
            actual = _canonical_environment(actual)
        if actual != expected[binding_field]:
            raise ReleaseEvidenceCaptureError(
                f"readyz {payload_field} does not match the trusted release identity "
                f"(expected {expected[binding_field]!r}, got {actual!r})"
            )


def _clean_and_attest(
    payload: Mapping[str, Any],
    *,
    binding: Mapping[str, str],
    captured_at: datetime,
    captured_now: bool,
    readyz: bool,
) -> dict[str, Any]:
    timestamp = _evidence_timestamp(
        payload,
        captured_at=captured_at,
        captured_now=captured_now,
    )
    _validate_declared_bindings(payload, expected=binding)
    if readyz:
        _validate_readyz(payload, expected=binding)

    attested = dict(payload)
    attested.pop("release_binding", None)
    meta = attested.get("meta")
    if isinstance(meta, Mapping) and "release_binding" in meta:
        cleaned_meta = dict(meta)
        cleaned_meta.pop("release_binding", None)
        attested["meta"] = cleaned_meta
    attested["generated_at"] = timestamp
    attested["release_binding"] = dict(binding)
    return attested


def _load_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ReleaseEvidenceCaptureError(f"input JSON path does not exist: {path}")
    if not path.is_file():
        raise ReleaseEvidenceCaptureError(f"input JSON path is not a file: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseEvidenceCaptureError(f"failed to read input JSON {path}: {exc}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReleaseEvidenceCaptureError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseEvidenceCaptureError(f"{path} must contain a top-level JSON object")
    return payload


def _resolve_output_paths(
    inputs: Sequence[Path],
    *,
    in_place: bool,
    output_path: str | Path | None,
    output_dir: str | Path | None,
) -> list[Path]:
    mode_count = sum((in_place, output_path is not None, output_dir is not None))
    if mode_count != 1:
        raise ReleaseEvidenceCaptureError(
            "choose exactly one output mode: in_place, output_path, or output_dir"
        )
    if output_path is not None:
        if len(inputs) != 1:
            raise ReleaseEvidenceCaptureError("output_path requires exactly one input JSON")
        outputs = [Path(output_path)]
    elif output_dir is not None:
        directory = Path(output_dir)
        outputs = [directory / source.name for source in inputs]
    else:
        outputs = list(inputs)

    normalized = [path.resolve(strict=False) for path in outputs]
    if len(set(normalized)) != len(normalized):
        raise ReleaseEvidenceCaptureError("multiple inputs resolve to the same output path")
    for target in outputs:
        if target.exists() and not target.is_file():
            raise ReleaseEvidenceCaptureError(f"output path is not a file: {target}")
        parent = target.parent
        if parent.exists() and not parent.is_dir():
            raise ReleaseEvidenceCaptureError(f"output parent is not a directory: {parent}")
    return outputs


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        mode = path.stat().st_mode if path.exists() else 0o644
        os.chmod(temporary_path, mode)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            file_descriptor = -1
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        temporary_path.unlink(missing_ok=True)
        raise


def capture_json_files(
    input_paths: Sequence[str | Path],
    *,
    in_place: bool = False,
    output_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    readyz_paths: Sequence[str | Path] = (),
    captured_now: bool = False,
    env: Mapping[str, str] | None = None,
) -> list[Path]:
    """Validate, attest, and atomically write one or more raw JSON evidence files."""

    inputs = [Path(path) for path in input_paths]
    if not inputs:
        raise ReleaseEvidenceCaptureError("at least one input JSON path is required")
    outputs = _resolve_output_paths(
        inputs,
        in_place=in_place,
        output_path=output_path,
        output_dir=output_dir,
    )
    binding = _release_binding(os.environ if env is None else env)
    captured_at = _capture_time()

    normalized_inputs = {path.resolve(strict=False) for path in inputs}
    explicit_readyz = {Path(path).resolve(strict=False) for path in readyz_paths}
    unknown_readyz = explicit_readyz - normalized_inputs
    if unknown_readyz:
        rendered = ", ".join(str(path) for path in sorted(unknown_readyz))
        raise ReleaseEvidenceCaptureError(
            f"explicit readyz paths must also be input JSON paths: {rendered}"
        )

    prepared: list[tuple[Path, dict[str, Any]]] = []
    for source, target in zip(inputs, outputs, strict=True):
        payload = _load_object(source)
        is_readyz = source.resolve(strict=False) in explicit_readyz or _looks_like_readyz(
            source, payload
        )
        attested = _clean_and_attest(
            payload,
            binding=binding,
            captured_at=captured_at,
            captured_now=captured_now,
            readyz=is_readyz,
        )
        prepared.append((target, attested))

    for target, payload in prepared:
        _atomic_write_json(target, payload)
    return [target for target, _payload in prepared]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Raw JSON evidence files to attest.")
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument(
        "--in-place",
        action="store_true",
        help="Atomically replace each input after every input validates.",
    )
    output.add_argument("--output", help="Output path for a single input JSON.")
    output.add_argument(
        "--output-dir",
        help="Directory that receives one output per input basename.",
    )
    parser.add_argument(
        "--readyz",
        action="append",
        default=[],
        metavar="PATH",
        help="Treat an input as /readyz and cross-check its runtime identity. Repeatable.",
    )
    parser.add_argument(
        "--captured-now",
        action="store_true",
        help=(
            "Allow a timestamp-free live snapshot to use the current UTC capture time. "
            "Existing timestamps are always validated and preserved."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        written = capture_json_files(
            args.inputs,
            in_place=args.in_place,
            output_path=args.output,
            output_dir=args.output_dir,
            readyz_paths=args.readyz,
            captured_now=args.captured_now,
        )
    except ReleaseEvidenceCaptureError as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "failed"},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "captured": [str(path) for path in written],
                "count": len(written),
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
