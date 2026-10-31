#!/usr/bin/env bash
# Run a headless Claude Code agent backed by DeepSeek (Anthropic-compatible API).
# Usage: ds_agent.sh <workdir> <prompt-file> <log-file> [extra claude args...]
set -euo pipefail
workdir=$1; prompt_file=$2; log_file=$3; shift 3
repo="$(cd "$(dirname "$0")/../.." && pwd)"
key=$(grep -E '^DEEPSEEK_API_KEY=' "$repo/.focus_agent/local.env" | head -1 | cut -d= -f2- | tr -d '"'"'")
cd "$workdir"
# A separate config dir keeps the user's own Claude settings (gateway, headers,
# apiKeyHelper) from overriding the DeepSeek endpoint.
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_MODEL -u ANTHROPIC_CUSTOM_HEADERS \
  -u ANTHROPIC_DEFAULT_FABLE_MODEL -u CLAUDE_CODE_GATEWAY_HINT_HEADERS -u CLAUDE_CODE_AUTO_MODE_SERVER \
  -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_MESSAGING_SOCKET -u CLAUDE_CODE_MESSAGING_TOKEN \
  -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_MAX_CONTEXT_TOKENS \
  -u CLAUDE_CODE_AUTO_COMPACT_WINDOW -u CLAUDE_AGENT_SDK_VERSION -u CLAUDE_EFFORT \
  CLAUDE_CONFIG_DIR="${FOCUS_AGENT_DS_CLAUDE_CONFIG:-$HOME/.config/focus-agent-ds-claude}" \
  ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic" \
  ANTHROPIC_AUTH_TOKEN="$key" \
  ANTHROPIC_MODEL="deepseek-v4-pro" \
  ANTHROPIC_SMALL_FAST_MODEL="deepseek-v4-pro" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-pro" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-pro" \
  CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-pro" \
  API_TIMEOUT_MS=600000 \
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  claude -p "$(cat "$prompt_file")" \
    --model deepseek-v4-pro \
    --permission-mode bypassPermissions \
    --output-format stream-json --verbose \
    "$@" < /dev/null > "$log_file" 2>&1
