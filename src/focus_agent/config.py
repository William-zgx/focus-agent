from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import MutableMapping


DEFAULT_LOCAL_CONFIG_DOC = ".focus_agent/local-model-config.md"
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


def load_local_env_document(
    path: str | Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    target_env = environ if environ is not None else os.environ
    resolved = Path(
        path
        or target_env.get("FOCUS_AGENT_LOCAL_CONFIG_DOC")
        or DEFAULT_LOCAL_CONFIG_DOC
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


@dataclass(slots=True)
class Settings:
    model: str = "openai:gpt-4.1-mini"
    model_choices: tuple[str, ...] = ()
    temperature: float = 0.0
    database_uri: str | None = None
    langgraph_api_url: str | None = None
    langsmith_project: str = "focus-agent"
    branch_db_path: str = ".focus_agent/branches.sqlite3"
    artifact_dir: str = "./artifacts"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_reload: bool = False
    app_version: str = "1.0.0"
    auth_enabled: bool = True
    auth_demo_tokens_enabled: bool = True
    auth_jwt_secret: str = "focus-agent-dev-secret"
    auth_jwt_issuer: str = "focus-agent"
    auth_access_token_ttl_seconds: int = 8 * 60 * 60
    sse_heartbeat_seconds: float = 1.5
    local_checkpoint_path: str | None = None
    local_store_path: str | None = None
    branch_max_depth: int = 5
    skill_directories: tuple[str, ...] = (".focus_agent/skills",)
    workspace_root: str = "."

    @classmethod
    def from_env(cls) -> "Settings":
        process_env = dict(os.environ)
        local_overrides = load_local_env_document(
            process_env.get("FOCUS_AGENT_LOCAL_CONFIG_DOC"),
            environ={},
        )
        env = {**local_overrides, **process_env}
        defaults = cls()
        database_uri = env.get("DATABASE_URI") or None
        langgraph_api_url = env.get("LANGGRAPH_API_URL") or None
        instance = cls(
            model=env.get("MODEL", defaults.model),
            model_choices=(
                _split_csv(env.get("FOCUS_AGENT_MODEL_CHOICES"))
                if env.get("FOCUS_AGENT_MODEL_CHOICES") is not None
                else defaults.model_choices
            ),
            temperature=float(env.get("TEMPERATURE", str(defaults.temperature))),
            database_uri=database_uri,
            langgraph_api_url=langgraph_api_url,
            langsmith_project=env.get("LANGSMITH_PROJECT", defaults.langsmith_project),
            branch_db_path=env.get("BRANCH_DB_PATH", defaults.branch_db_path),
            artifact_dir=env.get("ARTIFACT_DIR", defaults.artifact_dir),
            api_host=env.get("API_HOST", defaults.api_host),
            api_port=int(env.get("API_PORT", str(defaults.api_port))),
            api_reload=env.get("API_RELOAD", "false").lower() in {"1", "true", "yes", "on"},
            app_version=env.get("APP_VERSION", defaults.app_version),
            auth_enabled=env.get("AUTH_ENABLED", "true").lower() in {"1", "true", "yes", "on"},
            auth_demo_tokens_enabled=env.get("AUTH_DEMO_TOKENS_ENABLED", "true").lower()
            in {"1", "true", "yes", "on"},
            auth_jwt_secret=env.get("AUTH_JWT_SECRET", defaults.auth_jwt_secret),
            auth_jwt_issuer=env.get("AUTH_JWT_ISSUER", defaults.auth_jwt_issuer),
            auth_access_token_ttl_seconds=int(
                env.get(
                    "AUTH_ACCESS_TOKEN_TTL_SECONDS",
                    str(defaults.auth_access_token_ttl_seconds),
                )
            ),
            sse_heartbeat_seconds=float(
                env.get("SSE_HEARTBEAT_SECONDS", str(defaults.sse_heartbeat_seconds))
            ),
            local_checkpoint_path=env.get("LOCAL_CHECKPOINT_PATH") or None,
            local_store_path=env.get("LOCAL_STORE_PATH") or None,
            branch_max_depth=int(env.get("BRANCH_MAX_DEPTH", str(defaults.branch_max_depth))),
            skill_directories=(
                _split_csv(env.get("FOCUS_AGENT_SKILLS_DIRS"))
                if env.get("FOCUS_AGENT_SKILLS_DIRS") is not None
                else defaults.skill_directories
            ),
            workspace_root=env.get("WORKSPACE_ROOT", defaults.workspace_root),
        )
        Path(instance.branch_db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        Path(instance.artifact_dir).expanduser().mkdir(parents=True, exist_ok=True)
        return instance
