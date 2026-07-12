"""Stream-event loading and release-evidence validation for production smoke."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from scripts.release_evidence_binding import (
    DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    FUTURE_TIMESTAMP_TOLERANCE_SECONDS,
    _timestamp_from_payload,
)
from scripts.release_identity import RELEASE_IDENTITY_ENV

KNOWN_STREAM_EVENT_NAMES = {
    "message.completed",
    "message.delta",
    "reasoning.delta",
    "run.closed",
    "run.completed",
    "run.failed",
    "run.interrupt",
    "run.metadata",
    "run.status",
    "state.update",
    "task.update",
    "tool.call.delta",
    "tool.error",
    "tool.requested",
    "tool.result",
}
REQUIRED_STREAM_TERMINAL_EVENT = "run.completed"
FAILED_STREAM_TERMINAL_EVENTS = {"run.failed"}
STREAM_RELEASE_BINDING_FIELDS = tuple(RELEASE_IDENTITY_ENV)

HttpStreamLoader = Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]]


def _safe_headers(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        items = headers.items()
    except AttributeError:
        return {}
    return {str(key): str(value) for key, value in items}


def http_stream_events(
    url: str,
    *,
    auth_token: str | None,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    headers = {"Accept": "text/event-stream"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    request = urllib_request.Request(url, headers=headers, method="GET")
    with urllib_request.urlopen(request, timeout=timeout_seconds) as response:
        raw = _read_sse_sample(response)
        source = {
            "type": "live_url",
            "url": url,
            "status_code": int(getattr(response, "status", 0) or 0),
            "response_headers": _safe_headers(getattr(response, "headers", None)),
        }
        return _parse_sse_events(raw), source


def _read_sse_sample(response: Any) -> str:
    if not hasattr(response, "readline"):
        return response.read(256 * 1024).decode("utf-8", errors="replace")

    lines: list[str] = []
    for _index in range(1000):
        line_bytes = response.readline()
        if not line_bytes:
            break
        line = line_bytes.decode("utf-8", errors="replace")
        lines.append(line)
        if line in {"\n", "\r\n"}:
            events = _parse_sse_events("".join(lines))
            if any(
                event.get("event")
                in {REQUIRED_STREAM_TERMINAL_EVENT, *FAILED_STREAM_TERMINAL_EVENTS}
                for event in events
            ):
                break
        if sum(len(item) for item in lines) >= 256 * 1024:
            break
    return "".join(lines)


def _parse_sse_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_name = "message"
    data_lines: list[str] = []
    for line in raw.splitlines():
        if not line:
            if data_lines:
                events.append(_event_from_sse_frame(event_name, data_lines))
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
    if data_lines:
        events.append(_event_from_sse_frame(event_name, data_lines))
    return events


def _event_from_sse_frame(event_name: str, data_lines: Sequence[str]) -> dict[str, Any]:
    raw_data = "\n".join(data_lines)
    try:
        payload = json.loads(raw_data)
    except json.JSONDecodeError:
        payload = raw_data
    return {"event": event_name, "data": payload, "raw": raw_data}


def _events_from_json_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if "event" in payload:
        return [payload]
    stream_events = payload.get("stream_events")
    if isinstance(stream_events, dict) and isinstance(stream_events.get("events"), list):
        return list(stream_events["events"])
    if isinstance(stream_events, list):
        return list(stream_events)
    events = payload.get("events")
    return list(events) if isinstance(events, list) else []


def _canonical_environment(value: str) -> str:
    normalized = value.strip().lower()
    return "production" if normalized == "prod" else normalized


def _release_identity_configuration() -> tuple[str, dict[str, str]]:
    values = {
        field: str(os.environ.get(env_name) or "").strip()
        for field, env_name in RELEASE_IDENTITY_ENV.items()
    }
    configured = {field: value for field, value in values.items() if value}
    if not configured:
        return "absent", {}
    if len(configured) != len(RELEASE_IDENTITY_ENV):
        return "partial", {}
    configured["environment"] = _canonical_environment(configured["environment"])
    return "complete", configured


def _stream_release_binding(payload: Mapping[str, Any]) -> dict[str, str]:
    binding: Any = payload.get("release_binding")
    if not isinstance(binding, Mapping):
        meta = payload.get("meta")
        binding = meta.get("release_binding") if isinstance(meta, Mapping) else None
    if not isinstance(binding, Mapping):
        return {}
    result = {
        field: str(binding.get(field) or "").strip() for field in STREAM_RELEASE_BINDING_FIELDS
    }
    if result["environment"]:
        result["environment"] = _canonical_environment(result["environment"])
    return {field: value for field, value in result.items() if value}


def _stream_evidence_validation(
    payload: Any,
    *,
    generated_at: datetime,
) -> tuple[dict[str, Any], list[str]]:
    configuration, expected_binding = _release_identity_configuration()
    validation: dict[str, Any] = {
        "identity_configuration": configuration,
        "max_age_seconds": DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
        "required": configuration == "complete",
        "trusted": False,
    }
    if configuration != "complete":
        validation["status"] = "untrusted" if configuration == "partial" else "not-required"
        return validation, []

    errors: list[str] = []
    if not isinstance(payload, dict):
        errors.append("production stream event evidence must be a JSON object")
        validation.update(
            {
                "declared_binding": {},
                "expected_binding": expected_binding,
                "status": "failed",
            }
        )
        return validation, errors

    timestamp, timestamp_source, timestamp_error = _timestamp_from_payload(payload)
    if timestamp_error is not None:
        errors.append(f"stream evidence timestamp is invalid: {timestamp_error}")
    elif timestamp is None:
        errors.append("stream evidence timestamp is missing")

    age_seconds: float | None = None
    if timestamp is not None:
        age_seconds = (generated_at - timestamp).total_seconds()
        if age_seconds > DEFAULT_MAX_EVIDENCE_AGE_SECONDS:
            errors.append(
                "stream evidence is stale: "
                f"age {age_seconds:.3f}s exceeds {DEFAULT_MAX_EVIDENCE_AGE_SECONDS}s"
            )
        if age_seconds < -FUTURE_TIMESTAMP_TOLERANCE_SECONDS:
            errors.append("stream evidence timestamp is too far in the future")

    declared_binding = _stream_release_binding(payload)
    for field in STREAM_RELEASE_BINDING_FIELDS:
        if field not in declared_binding:
            errors.append(f"stream evidence release_binding is missing {field}")
            continue
        if declared_binding[field] != expected_binding[field]:
            errors.append(
                "stream evidence release_binding mismatch for "
                f"{field}: expected {expected_binding[field]!r}, "
                f"got {declared_binding[field]!r}"
            )

    passed = not errors
    validation.update(
        {
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "declared_binding": declared_binding,
            "expected_binding": expected_binding,
            "status": "passed" if passed else "failed",
            "timestamp": (
                timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
                if timestamp is not None
                else None
            ),
            "timestamp_source": timestamp_source,
            "trusted": passed,
        }
    )
    return validation, errors


def _normalize_stream_event(item: Any, *, index: int) -> tuple[dict[str, Any] | None, str | None]:
    if isinstance(item, str):
        return {"event": item, "data": {}}, None
    if not isinstance(item, dict):
        return None, f"event[{index}] must be an object or event name string"
    event_name = str(item.get("event") or item.get("name") or "").strip()
    if not event_name:
        return None, f"event[{index}] is missing event"
    data = item.get("data", {})
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return None, f"event[{index}] data must be an object"
    return {"event": event_name, "data": data}, None


def _validate_stream_events(
    events: Sequence[Any],
    *,
    evidence_errors: Sequence[str] = (),
    source: dict[str, Any],
) -> dict[str, Any]:
    normalized_events: list[dict[str, Any]] = []
    errors = list(evidence_errors)
    for index, item in enumerate(events):
        event, error = _normalize_stream_event(item, index=index)
        if error:
            errors.append(error)
            continue
        if event is not None:
            normalized_events.append(event)

    events_seen = [event["event"] for event in normalized_events]
    unique_events = sorted(set(events_seen))
    unknown_events = sorted(
        {event_name for event_name in events_seen if event_name not in KNOWN_STREAM_EVENT_NAMES}
    )
    if unknown_events:
        errors.append(f"unknown stream events: {', '.join(unknown_events)}")
    if not normalized_events:
        errors.append("stream event report contains no events")
    if REQUIRED_STREAM_TERMINAL_EVENT not in events_seen:
        errors.append(f"missing required stream event: {REQUIRED_STREAM_TERMINAL_EVENT}")
    failed_terminals = sorted(FAILED_STREAM_TERMINAL_EVENTS.intersection(events_seen))
    if failed_terminals:
        errors.append(f"stream reported failure events: {', '.join(failed_terminals)}")

    passed = not errors
    return {
        "status": "passed" if passed else "failed",
        "passed": passed,
        "source": source,
        "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
        "known_event_count": len(KNOWN_STREAM_EVENT_NAMES),
        "event_count": len(normalized_events),
        "events_seen": unique_events,
        "errors": errors,
        "events": normalized_events[:25],
        "detail": "stream event contract validated"
        if passed
        else "stream event contract validation failed",
    }


def build_stream_events_report(
    *,
    auth_token: str | None,
    dry_run: bool,
    stream_events_json: str | Path | None,
    stream_events_url: str | None,
    timeout_seconds: float,
    http_stream_loader: HttpStreamLoader = http_stream_events,
) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry-run",
            "passed": True,
            "source": {
                "type": "planned",
                "json": str(stream_events_json) if stream_events_json else None,
                "url": stream_events_url,
            },
            "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
            "event_count": 0,
            "events_seen": [],
            "errors": [],
            "detail": "planned stream event contract validation",
        }
    if stream_events_json:
        path = Path(stream_events_json)
        try:
            raw_payload = path.read_bytes()
            payload = json.loads(raw_payload)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {
                "status": "failed",
                "passed": False,
                "source": {"type": "file", "path": str(path)},
                "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
                "event_count": 0,
                "events_seen": [],
                "errors": [str(exc)],
                "detail": "failed to load stream event report",
            }
        evidence_validation, evidence_errors = _stream_evidence_validation(
            payload,
            generated_at=datetime.now(UTC),
        )
        return _validate_stream_events(
            _events_from_json_payload(payload),
            evidence_errors=evidence_errors,
            source={
                "bytes": len(raw_payload),
                "type": "file",
                "path": str(path),
                "sha256": hashlib.sha256(raw_payload).hexdigest(),
                "evidence_validation": evidence_validation,
            },
        )
    if stream_events_url:
        try:
            events, source = http_stream_loader(
                stream_events_url,
                auth_token=auth_token,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, TimeoutError, urllib_error.URLError, urllib_error.HTTPError) as exc:
            return {
                "status": "failed",
                "passed": False,
                "source": {"type": "live_url", "url": stream_events_url},
                "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
                "event_count": 0,
                "events_seen": [],
                "errors": [str(exc)],
                "detail": "failed to load stream event URL",
            }
        return _validate_stream_events(events, source=source)
    return {
        "status": "failed",
        "passed": False,
        "source": {"type": "none"},
        "required_events": [REQUIRED_STREAM_TERMINAL_EVENT],
        "event_count": 0,
        "events_seen": [],
        "errors": ["stream event validation input is required in live mode"],
        "detail": "stream event validation input is required in live mode",
    }


__all__ = [
    "DEFAULT_MAX_EVIDENCE_AGE_SECONDS",
    "FAILED_STREAM_TERMINAL_EVENTS",
    "FUTURE_TIMESTAMP_TOLERANCE_SECONDS",
    "KNOWN_STREAM_EVENT_NAMES",
    "RELEASE_IDENTITY_ENV",
    "REQUIRED_STREAM_TERMINAL_EVENT",
    "build_stream_events_report",
    "http_stream_events",
]
