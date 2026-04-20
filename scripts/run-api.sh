#!/usr/bin/env bash

set -euo pipefail

SERVE_SCRIPT_NAME="${SERVE_SCRIPT_NAME:-api}"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/serve-common.sh"

cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

export PYTHONUNBUFFERED=1
export API_RELOAD="${API_RELOAD:-0}"
unset WATCHFILES_FORCE_POLLING || true

assert_api_binary
ensure_local_setup
load_local_env_exports
ensure_managed_database_uri

assert_port_free "$API_PORT" "API"

trap_managed_processes

log "Starting API on http://${API_HOST}:${API_PORT} (reload=${API_RELOAD})"
.venv/bin/focus-agent-api &
register_managed_pid "$!"

log "Press Ctrl+C to stop the API${DATABASE_URI:+ and managed local PostgreSQL}."

monitor_managed_processes
