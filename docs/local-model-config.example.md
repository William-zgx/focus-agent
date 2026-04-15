# Local Model Config

This file is meant to be copied to:

```text
.focus_agent/local-model-config.md
```

That local file is git-ignored, so it stays on your machine and does not get pushed.

Put model-related environment variables in the document as plain `KEY=VALUE` lines:

```env
MODEL=ollama:qwen2.5:7b
FOCUS_AGENT_MODEL_CHOICES=ollama:qwen2.5:7b,openai:gpt-4.1-mini,moonshot:kimi-k2.5
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_API_KEY=ollama
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=replace-me-locally
MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
MOONSHOT_API_KEY=replace-me-locally
TEMPERATURE=0
```

Notes:

- Process environment variables still win over this file.
- `ollama:<model>` uses the local Ollama OpenAI-compatible endpoint by default.
- You can override the file path with `FOCUS_AGENT_LOCAL_CONFIG_DOC`.
- The loader reads any `KEY=VALUE` lines in the document, so keep secrets only in the local ignored copy.
