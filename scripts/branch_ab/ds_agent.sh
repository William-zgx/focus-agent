#!/usr/bin/env bash
# Run a headless Claude Code agent backed by DeepSeek.
# Usage: ds_agent.sh <workdir> <prompt-file> <log-file> [extra claude args...]
# DS_BACKEND=gateway (default): devbox gateway, Anthropic /v1/messages, DeepSeek V4.1 Flash.
# DS_BACKEND=official: api.deepseek.com/anthropic with DEEPSEEK_API_KEY from local.env.
set -euo pipefail
workdir=$1; prompt_file=$2; log_file=$3; shift 3
repo="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ "${DS_BACKEND:-gateway}" == official ]]; then
  base_url="https://api.deepseek.com/anthropic"
  token=$(grep -E '^DEEPSEEK_API_KEY=' "$repo/.focus_agent/local.env" | head -1 | cut -d= -f2- | tr -d '"'"'")
  model="${DS_MODEL:-deepseek-v4-pro}"
  headers=""
else
  base_url="${DS_GATEWAY_URL:-https://10.251.247.136:18446}"
  token=$(/home/zouguoxue/.local/bin/codex-sg-api-key)
  model="${DS_MODEL:-traex-sg/DeepSeek-V4.1-Flash[1m]}"
  headers="x-claude-model-scope: cli"
  export NODE_EXTRA_CA_CERTS=/home/zouguoxue/.config/sg-model-gateway/claude-ca-bundle.pem
  export NO_PROXY="10.251.247.136,${NO_PROXY:-}" no_proxy="10.251.247.136,${no_proxy:-}"
fi
cd "$workdir"
# A separate config dir keeps the user's own Claude settings (gateway, headers,
# apiKeyHelper) from overriding this endpoint.
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_MODEL -u ANTHROPIC_CUSTOM_HEADERS \
  -u ANTHROPIC_DEFAULT_FABLE_MODEL -u CLAUDE_CODE_GATEWAY_HINT_HEADERS -u CLAUDE_CODE_AUTO_MODE_SERVER \
  -u CLAUDE_CODE_CHILD_SESSION -u CLAUDE_CODE_MESSAGING_SOCKET -u CLAUDE_CODE_MESSAGING_TOKEN \
  -u CLAUDE_CODE_SESSION_ID -u CLAUDE_CODE_ENTRYPOINT -u CLAUDE_CODE_MAX_CONTEXT_TOKENS \
  -u CLAUDE_CODE_AUTO_COMPACT_WINDOW -u CLAUDE_AGENT_SDK_VERSION -u CLAUDE_EFFORT \
  CLAUDE_CONFIG_DIR="${FOCUS_AGENT_DS_CLAUDE_CONFIG:-$HOME/.config/focus-agent-ds-claude}" \
  ANTHROPIC_BASE_URL="$base_url" \
  ANTHROPIC_AUTH_TOKEN="$token" \
  ANTHROPIC_CUSTOM_HEADERS="$headers" \
  ANTHROPIC_MODEL="$model" \
  ANTHROPIC_SMALL_FAST_MODEL="$model" \
  ANTHROPIC_DEFAULT_OPUS_MODEL="$model" \
  ANTHROPIC_DEFAULT_SONNET_MODEL="$model" \
  ANTHROPIC_DEFAULT_HAIKU_MODEL="$model" \
  CLAUDE_CODE_SUBAGENT_MODEL="$model" \
  API_TIMEOUT_MS=600000 \
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
  claude -p "$(cat "$prompt_file")" \
    --model "$model" \
    --permission-mode bypassPermissions \
    --output-format stream-json --verbose \
    "$@" < /dev/null > "$log_file" 2>&1
