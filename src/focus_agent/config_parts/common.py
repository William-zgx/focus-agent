from __future__ import annotations

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
