#!/usr/bin/env bash

set -euo pipefail

SERVE_SCRIPT_NAME="serve-dev"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/serve-common.sh"

cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
WEB_HOST="${FOCUS_AGENT_WEB_HOST:-127.0.0.1}"
WEB_PORT="${FOCUS_AGENT_WEB_PORT:-5173}"

export PYTHONUNBUFFERED=1
export API_RELOAD="${API_RELOAD:-1}"
if [[ -n "${WATCHFILES_FORCE_POLLING:-}" ]]; then
  export WATCHFILES_FORCE_POLLING
fi
export WEB_APP_DEV_SERVER_URL="${WEB_APP_DEV_SERVER_URL:-http://${WEB_HOST}:${WEB_PORT}/app}"

require_command pnpm
assert_api_binary
assert_workspace_node_modules
ensure_local_setup
load_local_env_exports
enable_local_embedding_auto_pull_default
normalize_no_proxy_for_httpx
ensure_managed_database_uri

assert_port_free "$API_PORT" "API"
assert_port_free "$WEB_PORT" "Web"

trap_managed_processes

log "Starting API on http://${API_HOST}:${API_PORT} (reload=${API_RELOAD})"
.venv/bin/focus-agent-api &
register_managed_pid "$!"

log "Starting Web app on http://${WEB_HOST}:${WEB_PORT}/app/ (Vite HMR enabled)"
pnpm --filter @focus-agent/web-app exec vite --host "$WEB_HOST" --port "$WEB_PORT" &
register_managed_pid "$!"

log "Backend /app redirect target: ${WEB_APP_DEV_SERVER_URL}"
log "Press Ctrl+C to stop both processes."

monitor_managed_processes
