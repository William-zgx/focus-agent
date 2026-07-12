from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from focus_agent.api.contract_models.admin_config import AdminConfigSourceResponse

from focus_agent.config import (
    DEFAULT_LOCAL_ENV_FILE,
    DEFAULT_MODEL_CATALOG_DOC,
    DEFAULT_TOOL_CATALOG_DOC,
)

_ENV_ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=\s*(.*)$")


def _admin_config_contracts():
    return importlib.import_module("focus_agent.api.contract_models.admin_config")


def _write_local_env_updates(path: Path, updates: dict[str, object | None]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in existing_lines:
        match = _ENV_ASSIGNMENT_RE.match(line.strip())
        if match and match.group(1) in updates:
            key = match.group(1)
            seen.add(key)
            value = updates[key]
            if value is not None:
                next_lines.append(f"{key}={_format_env_value(value)}")
            continue
        next_lines.append(line)

    missing = [(key, value) for key, value in updates.items() if key not in seen]
    if missing and next_lines and next_lines[-1].strip():
        next_lines.append("")
    if missing and not existing_lines:
        next_lines.append("# Managed by Focus Agent admin config.")
    for key, value in missing:
        if value is not None:
            next_lines.append(f"{key}={_format_env_value(value)}")

    _write_text_atomic(path, "\n".join(next_lines).rstrip() + "\n")


def _format_env_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _settings_env(settings: Any) -> dict[str, str]:
    return dict(getattr(settings, "resolved_env", {}) or {})


def _configured_env_value(
    env: dict[str, str],
    env_key: str | None,
    default_value: str | None,
) -> bool:
    return bool(default_value or (env_key and (env.get(env_key) or os.environ.get(env_key))))


def _model_catalog_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_MODEL_CATALOG_DOC")
        or os.environ.get("FOCUS_AGENT_MODEL_CATALOG_DOC")
        or DEFAULT_MODEL_CATALOG_DOC
    ).expanduser()


def _tool_catalog_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_TOOL_CATALOG_DOC")
        or os.environ.get("FOCUS_AGENT_TOOL_CATALOG_DOC")
        or DEFAULT_TOOL_CATALOG_DOC
    ).expanduser()


def _local_env_path(settings: Any) -> Path:
    env = _settings_env(settings)
    return Path(
        env.get("FOCUS_AGENT_LOCAL_ENV_FILE")
        or os.environ.get("FOCUS_AGENT_LOCAL_ENV_FILE")
        or DEFAULT_LOCAL_ENV_FILE
    ).expanduser()


def _source_response(path: Path) -> AdminConfigSourceResponse:
    contracts = _admin_config_contracts()
    return contracts.AdminConfigSourceResponse(
        path=str(path),
        exists=path.exists(),
        writable=_path_writable(path),
    )


def _path_writable(path: Path) -> bool:
    if path.exists():
        return os.access(path, os.W_OK)
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    return os.access(parent, os.W_OK)
