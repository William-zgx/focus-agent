#!/bin/bash
set -eu

cd "$(dirname "$0")/.."
uv run python scripts/export-openapi.py
pnpm --filter @focus-agent/web-sdk exec openapi-typescript ../docs/api/openapi.json -o src/types/__generated__.ts
echo "SDK types generated."
