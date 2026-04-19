#!/bin/sh

set -eu

DATA_DIR="${FOCUS_AGENT_DATA_DIR:-/data}"
DEFAULTS_DIR="/opt/focus-agent/defaults"

copy_if_missing() {
  target="$1"
  source="$2"

  if [ -e "$target" ] || [ ! -f "$source" ]; then
    return 0
  fi

  mkdir -p "$(dirname "$target")"
  cp "$source" "$target"
}

mkdir -p "$DATA_DIR"

copy_if_missing "$DATA_DIR/local.env" "$DEFAULTS_DIR/local.env"
copy_if_missing "$DATA_DIR/models.toml" "$DEFAULTS_DIR/models.toml"
copy_if_missing "$DATA_DIR/tools.toml" "$DEFAULTS_DIR/tools.toml"

export FOCUS_AGENT_LOCAL_ENV_FILE="${FOCUS_AGENT_LOCAL_ENV_FILE:-$DATA_DIR/local.env}"
export FOCUS_AGENT_MODEL_CATALOG_DOC="${FOCUS_AGENT_MODEL_CATALOG_DOC:-$DATA_DIR/models.toml}"
export FOCUS_AGENT_TOOL_CATALOG_DOC="${FOCUS_AGENT_TOOL_CATALOG_DOC:-$DATA_DIR/tools.toml}"
export BRANCH_DB_PATH="${BRANCH_DB_PATH:-$DATA_DIR/branches.sqlite3}"
export ARTIFACT_DIR="${ARTIFACT_DIR:-$DATA_DIR/artifacts}"
export LOCAL_CHECKPOINT_PATH="${LOCAL_CHECKPOINT_PATH:-$DATA_DIR/langgraph-checkpoints.pkl}"
export LOCAL_STORE_PATH="${LOCAL_STORE_PATH:-$DATA_DIR/langgraph-store.pkl}"
export API_HOST="${API_HOST:-0.0.0.0}"
export API_PORT="${API_PORT:-8000}"
export API_RELOAD="${API_RELOAD:-0}"

mkdir -p "$(dirname "$BRANCH_DB_PATH")"
mkdir -p "$ARTIFACT_DIR"
mkdir -p "$(dirname "$LOCAL_CHECKPOINT_PATH")"
mkdir -p "$(dirname "$LOCAL_STORE_PATH")"

exec "$@"
