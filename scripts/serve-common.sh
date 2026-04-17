#!/usr/bin/env bash

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
managed_pids=()

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
