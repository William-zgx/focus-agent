#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
managed_pids=()
managed_cleanup_callbacks=()

log() {
  local prefix="${SERVE_SCRIPT_NAME:-serve}"
  printf '[%s] %s\n' "$prefix" "$*"
}

die() {
  local prefix="${SERVE_SCRIPT_NAME:-serve}"
  printf '[%s] Error: %s\n' "$prefix" "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

ensure_local_file() {
  local target="$1"
  local source="$2"

  if [[ -f "$target" ]]; then
    return 0
  fi
  if [[ ! -f "$source" ]]; then
    die "Missing template file: $source"
  fi

  mkdir -p "$(dirname "$target")"
  cp "$source" "$target"
  log "Created $target from $source"
}

ensure_local_setup() {
  ensure_local_file ".env" ".env.example"
  ensure_local_file ".focus_agent/local.env" "docs/local.env.example"
  ensure_local_file ".focus_agent/models.toml" "docs/models.example.toml"
  ensure_local_file ".focus_agent/tools.toml" "docs/tools.example.toml"
}

assert_api_binary() {
  [[ -x ".venv/bin/focus-agent-api" ]] || die "Missing .venv/bin/focus-agent-api. Run 'make install' first."
}

assert_workspace_node_modules() {
  [[ -d "node_modules" ]] || die "Missing node_modules. Run 'pnpm install --registry=https://registry.npmjs.org' first."
}

port_is_busy() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 1
  fi
  lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
}

assert_port_free() {
  local port="$1"
  local label="$2"
  if port_is_busy "$port"; then
    die "${label} port ${port} is already in use."
  fi
}

collect_descendants() {
  local parent_pid="$1"
  local child_pid

  if [[ -z "$parent_pid" ]] || ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  while IFS= read -r child_pid; do
    [[ -n "$child_pid" ]] || continue
    collect_descendants "$child_pid"
    printf '%s\n' "$child_pid"
  done < <(pgrep -P "$parent_pid" 2>/dev/null || true)
}

terminate_process_tree() {
  local parent_pid="$1"
  local child_pid

  if [[ -z "$parent_pid" ]] || ! kill -0 "$parent_pid" >/dev/null 2>&1; then
    return 0
  fi

  while IFS= read -r child_pid; do
    [[ -n "$child_pid" ]] || continue
    kill "$child_pid" >/dev/null 2>&1 || true
  done < <(collect_descendants "$parent_pid")

  kill "$parent_pid" >/dev/null 2>&1 || true
}

register_managed_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  managed_pids+=("$pid")
}

register_cleanup_callback() {
  local callback_name="$1"
  [[ -n "$callback_name" ]] || return 0
  managed_cleanup_callbacks+=("$callback_name")
}

cleanup_managed_processes() {
  local exit_code=$?
  local index

  trap - EXIT INT TERM

  for ((index=${#managed_pids[@]} - 1; index>=0; index--)); do
    terminate_process_tree "${managed_pids[$index]}"
  done

  for index in "${!managed_pids[@]}"; do
    wait "${managed_pids[$index]}" 2>/dev/null || true
  done

  for ((index=${#managed_cleanup_callbacks[@]} - 1; index>=0; index--)); do
    "${managed_cleanup_callbacks[$index]}" || true
  done

  exit "$exit_code"
}

trap_managed_processes() {
  trap cleanup_managed_processes EXIT INT TERM
}

monitor_managed_processes() {
  local pid
  while true; do
    for pid in "${managed_pids[@]}"; do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        wait "$pid"
      fi
    done
    sleep 1
  done
}

trim_whitespace() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

resolve_root_path() {
  local path="$1"
  if [[ "$path" = /* ]]; then
    printf '%s' "$path"
  else
    printf '%s/%s' "$ROOT_DIR" "$path"
  fi
}

load_local_env_exports() {
  local env_file="${FOCUS_AGENT_LOCAL_ENV_FILE:-.focus_agent/local.env}"
  local raw_line trimmed_line key raw_value value

  [[ -f "$env_file" ]] || return 0

  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    trimmed_line="$(trim_whitespace "$raw_line")"
    [[ -z "$trimmed_line" || "${trimmed_line:0:1}" == "#" ]] && continue
    if [[ "$trimmed_line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      raw_value="${BASH_REMATCH[2]}"
      value="$(trim_whitespace "$raw_value")"
      if [[ "$value" =~ ^\"(.*)\"$ ]]; then
        value="${BASH_REMATCH[1]}"
      elif [[ "$value" =~ ^\'(.*)\'$ ]]; then
        value="${BASH_REMATCH[1]}"
      fi
      if [[ -z "${!key+x}" ]]; then
        export "$key=$value"
      fi
    fi
  done < "$env_file"
}

pick_local_pg_port() {
  local requested_port="${FOCUS_AGENT_LOCAL_PG_PORT:-54329}"
  local candidate

  for candidate in $(seq "$requested_port" $((requested_port + 20))); do
    if ! port_is_busy "$candidate"; then
      printf '%s' "$candidate"
      return 0
    fi
  done

  die "Could not find a free local PostgreSQL port starting from ${requested_port}."
}

wait_for_local_postgres_ready() {
  local host="$1"
  local port="$2"
  local user="$3"
  local attempt

  for attempt in $(seq 1 50); do
    if psql "postgresql://${user}@${host}:${port}/postgres" -c 'select 1' >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

ensure_local_postgres_database() {
  local host="$1"
  local port="$2"
  local user="$3"
  local database="$4"

  if ! psql "postgresql://${user}@${host}:${port}/postgres" -Atqc \
    "SELECT 1 FROM pg_database WHERE datname = '${database}'" | grep -q '^1$'; then
    createdb -h "$host" -p "$port" -U "$user" "$database"
  fi
}

stop_managed_local_postgres() {
  [[ -n "${FOCUS_AGENT_MANAGED_PG_DATA_DIR:-}" ]] || return 0
  pg_ctl -D "$FOCUS_AGENT_MANAGED_PG_DATA_DIR" stop -m fast >/dev/null 2>&1 || true
  if [[ -n "${FOCUS_AGENT_MANAGED_PG_RUN_DIR:-}" && -n "${FOCUS_AGENT_MANAGED_PG_PORT:-}" ]]; then
    rm -f "${FOCUS_AGENT_MANAGED_PG_RUN_DIR}/.s.PGSQL.${FOCUS_AGENT_MANAGED_PG_PORT}"*
  fi
}

ensure_managed_database_uri() {
  local auto_local_pg="${FOCUS_AGENT_AUTO_LOCAL_POSTGRES:-1}"
  local data_dir run_dir log_file port host user database state_file

  if [[ -n "${DATABASE_URI:-}" ]]; then
    log "Using explicit DATABASE_URI from environment/local config"
    return 0
  fi

  if [[ "$auto_local_pg" == "0" || "$auto_local_pg" == "false" || "$auto_local_pg" == "no" ]]; then
    log "Automatic local PostgreSQL startup is disabled and DATABASE_URI is not set"
    return 0
  fi

  require_command initdb
  require_command pg_ctl
  require_command postgres
  require_command createdb
  require_command psql

  data_dir="$(resolve_root_path "${FOCUS_AGENT_LOCAL_PG_DATA_DIR:-.focus_agent/postgres/data}")"
  run_dir="$(resolve_root_path "${FOCUS_AGENT_LOCAL_PG_RUN_DIR:-.focus_agent/postgres/run}")"
  log_file="$(resolve_root_path "${FOCUS_AGENT_LOCAL_PG_LOG_FILE:-.focus_agent/postgres/postgres.log}")"
  state_file="$(resolve_root_path "${FOCUS_AGENT_LOCAL_PG_STATE_FILE:-.focus_agent/postgres/runtime.env}")"
  host="${FOCUS_AGENT_LOCAL_PG_HOST:-127.0.0.1}"
  user="${FOCUS_AGENT_LOCAL_PG_USER:-focus_agent}"
  database="${FOCUS_AGENT_LOCAL_PG_DB:-focus_agent}"

  mkdir -p "$data_dir" "$run_dir" "$(dirname "$log_file")" "$(dirname "$state_file")"

  if [[ ! -f "$data_dir/PG_VERSION" ]]; then
    log "Initializing local PostgreSQL data directory at ${data_dir}"
    initdb -D "$data_dir" --username="$user" --auth=trust >/dev/null
  fi

  if [[ -f "$data_dir/postmaster.pid" ]] && ! pg_ctl -D "$data_dir" status >/dev/null 2>&1; then
    rm -f "$data_dir/postmaster.pid"
  fi

  if pg_ctl -D "$data_dir" status >/dev/null 2>&1; then
    if [[ -f "$state_file" ]]; then
      # shellcheck disable=SC1090
      source "$state_file"
    fi
    port="${FOCUS_AGENT_MANAGED_PG_PORT:-${FOCUS_AGENT_LOCAL_PG_PORT:-54329}}"
    log "Reusing running local PostgreSQL from ${data_dir}"
  else
    port="$(pick_local_pg_port)"
    log "Starting managed local PostgreSQL on ${host}:${port}"
    pg_ctl -D "$data_dir" -l "$log_file" -o "-h ${host} -p ${port} -k ${run_dir}" start >/dev/null
  fi

  wait_for_local_postgres_ready "$host" "$port" "$user" || die "Managed local PostgreSQL did not become ready."
  ensure_local_postgres_database "$host" "$port" "$user" "$database"

  export DATABASE_URI="postgresql://${user}@${host}:${port}/${database}"
  export FOCUS_AGENT_MANAGED_PG_DATA_DIR="$data_dir"
  export FOCUS_AGENT_MANAGED_PG_RUN_DIR="$run_dir"
  export FOCUS_AGENT_MANAGED_PG_PORT="$port"
  cat > "$state_file" <<EOF
FOCUS_AGENT_MANAGED_PG_PORT=${port}
FOCUS_AGENT_MANAGED_PG_DATA_DIR=${data_dir}
FOCUS_AGENT_MANAGED_PG_RUN_DIR=${run_dir}
EOF
  register_cleanup_callback stop_managed_local_postgres
  log "Auto-configured DATABASE_URI=${DATABASE_URI}"
}
