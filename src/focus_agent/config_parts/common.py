from __future__ import annotations

import json
import os
import re
from collections.abc import MutableMapping
from pathlib import Path

DEFAULT_LOCAL_ENV_FILE = ".focus_agent/local.env"
_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")


def _normalize_config_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _split_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _split_key_value_csv(value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    pairs: dict[str, str] = {}
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        key, raw_value = part.split("=", 1)
        key = key.strip()
        resolved_value = raw_value.strip()
        if key and resolved_value:
            pairs[key] = resolved_value
    return pairs


def _parse_key_value_json_or_csv(value: str | None) -> dict[str, str]:
    if value is None:
        return {}
    text = value.strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key).strip(): str(item).strip()
            for key, item in payload.items()
            if str(key).strip() and str(item).strip()
        }
    return _split_key_value_csv(text)


def _normalize_optional_string(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_agent_delegation_execution_mode(value: object) -> str:
    from ..agent_execution import normalize_delegation_execution_mode

    return normalize_delegation_execution_mode(str(value or "observe"))


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None


def _env_bool(env: MutableMapping[str, str], name: str, *, default: bool) -> bool:
    return env.get(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


def load_local_env_file(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    target_env = environ if environ is not None else os.environ
    resolved = Path(
        path or target_env.get("FOCUS_AGENT_LOCAL_ENV_FILE") or DEFAULT_LOCAL_ENV_FILE
    ).expanduser()
    if not resolved.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        match = _ENV_ASSIGNMENT_RE.match(raw_line.strip())
        if not match:
            continue
        key, raw_value = match.groups()
        value = _normalize_config_value(raw_value)
        loaded[key] = value
        target_env.setdefault(key, value)
    return loaded
