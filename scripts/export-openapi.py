from __future__ import annotations

import json
from pathlib import Path

from focus_agent.api.main import create_app


def main() -> None:
    output_path = Path("docs/api/openapi.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    output_path.write_text(f"{json.dumps(schema, indent=2, sort_keys=True)}\n", encoding="utf-8")
    print(f"Exported OpenAPI schema: {len(schema.get('paths', {}))} paths")


if __name__ == "__main__":
    main()
