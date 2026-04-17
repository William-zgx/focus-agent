#!/usr/bin/env bash

set -euo pipefail

SERVE_SCRIPT_NAME="serve-prod"
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/serve-common.sh"

cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

export PYTHONUNBUFFERED=1
export API_RELOAD=0
export WEB_APP_DEV_SERVER_URL=""
unset WATCHFILES_FORCE_POLLING || true

require_command pnpm
assert_api_binary
assert_workspace_node_modules
ensure_local_setup

assert_port_free "$API_PORT" "API"

log "Building static frontend bundle for production serving"
pnpm web:build

log "Starting API on http://${API_HOST}:${API_PORT} (reload=0, static frontend)"
log "Frontend will be served by FastAPI at /app"

exec .venv/bin/focus-agent-api
