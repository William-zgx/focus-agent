#!/usr/bin/env python3
"""Check API and frontend SDK compatibility snapshots."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
API_SNAPSHOT_PATH = REPO_ROOT / "tests" / "contracts" / "api_routes.json"
SDK_SNAPSHOT_PATH = REPO_ROOT / "tests" / "contracts" / "frontend_sdk.json"
SDK_CLIENT_PATH = REPO_ROOT / "frontend-sdk" / "src" / "client.ts"
SDK_TYPES_PATH = REPO_ROOT / "frontend-sdk" / "src" / "types.ts"
SDK_REDUCERS_PATH = REPO_ROOT / "frontend-sdk" / "src" / "reducers.ts"
SDK_INDEX_PATH = REPO_ROOT / "frontend-sdk" / "src" / "index.ts"
WEB_SRC_PATH = REPO_ROOT / "apps" / "web" / "src"


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(payload), encoding="utf-8")


def _schema_signature(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return {"$ref": schema["$ref"]}
    kept: dict[str, Any] = {}
    for key in (
        "type",
        "format",
        "enum",
        "const",
        "required",
        "default",
        "nullable",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    ):
        if key in schema:
            kept[key] = schema[key]
    if "items" in schema:
        kept["items"] = _schema_signature(schema["items"])
    if "additionalProperties" in schema:
        additional = schema["additionalProperties"]
        kept["additionalProperties"] = (
            _schema_signature(additional) if isinstance(additional, dict) else additional
        )
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema and isinstance(schema[key], list):
            kept[key] = [_schema_signature(item) for item in schema[key]]
    if "properties" in schema and isinstance(schema["properties"], dict):
        kept["properties"] = {
            name: _schema_signature(value)
            for name, value in sorted(schema["properties"].items())
        }
    return kept or schema


def _parameter_signature(parameter: dict[str, Any]) -> dict[str, Any]:
    content_schema = _content_schema(parameter)
    return {
        "name": str(parameter.get("name") or ""),
        "in": str(parameter.get("in") or ""),
        "required": bool(parameter.get("required", False)),
        "deprecated": bool(parameter.get("deprecated", False)),
        "style": parameter.get("style"),
        "explode": parameter.get("explode"),
        "schema": _schema_signature(parameter.get("schema")),
        "content": content_schema,
    }


def _content_schema(payload: dict[str, Any] | None) -> Any:
    if not isinstance(payload, dict):
        return None
    content = payload.get("content")
    if not isinstance(content, dict):
        return None
    media = content.get("application/json") or content.get("text/event-stream")
    if not isinstance(media, dict):
        return None
    return _schema_signature(media.get("schema"))


def build_api_contract() -> dict[str, Any]:
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from focus_agent.api.main import create_app

    openapi = create_app().openapi()
    routes: list[dict[str, Any]] = []
    for path, operations in sorted((openapi.get("paths") or {}).items()):
        if not isinstance(operations, dict):
            continue
        for method, operation in sorted(operations.items()):
            if method.lower() not in {"delete", "get", "patch", "post", "put"}:
                continue
            if not isinstance(operation, dict):
                continue
            responses = {}
            for status, response in sorted((operation.get("responses") or {}).items()):
                if isinstance(response, dict):
                    responses[str(status)] = _content_schema(response)
            routes.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": str(operation.get("operationId") or ""),
                    "parameters": [
                        _parameter_signature(parameter)
                        for parameter in operation.get("parameters", [])
                        if isinstance(parameter, dict)
                    ],
                    "request": _content_schema(operation.get("requestBody")),
                    "responses": responses,
                }
            )
    component_schemas = openapi.get("components", {}).get("schemas", {})
    schemas = {
        name: _schema_signature(schema)
        for name, schema in sorted(component_schemas.items())
        if isinstance(schema, dict)
    }
    return {"version": 1, "routes": routes, "schemas": schemas}


def _class_body(source: str, class_name: str) -> str:
    match = re.search(rf"export\s+class\s+{re.escape(class_name)}\b", source)
    if not match:
        return ""
    body_start = source.find("{", match.end())
    if body_start < 0:
        return ""
    depth = 0
    for index in range(body_start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[body_start + 1 : index]
    return source[body_start + 1 :]


def _exported_type_names(source: str) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"^export\s+(?:interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                source,
                flags=re.MULTILINE,
            )
        )
    )


def _event_names(types_source: str) -> list[str]:
    match = re.search(
        r"export\s+type\s+FocusAgentEventName\s*=\s*(.*?);",
        types_source,
        flags=re.DOTALL,
    )
    if not match:
        return []
    return sorted(set(re.findall(r'"([^"]+)"', match.group(1))))


def _normalize_ts_declaration(value: str) -> str:
    return " ".join(value.replace("\n", " ").split())


def _scan_braced_exports(source: str, keyword: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    pattern = re.compile(rf"export\s+{keyword}\s+([A-Za-z_][A-Za-z0-9_]*)\b")
    for match in pattern.finditer(source):
        name = match.group(1)
        body_start = source.find("{", match.end())
        if body_start < 0:
            continue
        depth = 0
        for index in range(body_start, len(source)):
            char = source[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    declarations[name] = _normalize_ts_declaration(source[match.start() : index + 1])
                    break
    return declarations


def _scan_type_exports(source: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    pattern = re.compile(r"export\s+type\s+([A-Za-z_][A-Za-z0-9_]*)\b")
    for match in pattern.finditer(source):
        name = match.group(1)
        end = _find_type_alias_end(source, match.end())
        declarations[name] = _normalize_ts_declaration(source[match.start() : end + 1])
    return declarations


def _find_type_alias_end(source: str, start: int) -> int:
    depth = {"{": 0, "[": 0, "(": 0}
    quote: str | None = None
    escaped = False
    index = start
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {'"', "'", "`"}:
            quote = char
        elif char == "{":
            depth["{"] += 1
        elif char == "}":
            depth["{"] = max(0, depth["{"] - 1)
        elif char == "[":
            depth["["] += 1
        elif char == "]":
            depth["["] = max(0, depth["["] - 1)
        elif char == "(":
            depth["("] += 1
        elif char == ")":
            depth["("] = max(0, depth["("] - 1)
        elif char == ";" and all(value == 0 for value in depth.values()):
            return index
        index += 1
    return len(source) - 1


def _public_method_signatures(client_body: str) -> dict[str, str]:
    signatures: dict[str, str] = {}
    pattern = re.compile(
        r"^\s{2}(async\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([\s\S]*?\)\s*:[^{]+)\{",
        flags=re.MULTILINE,
    )
    for match in pattern.finditer(client_body):
        name = match.group(2)
        if name.startswith("_"):
            continue
        signatures[name] = _normalize_ts_declaration(match.group(1))
    return dict(sorted(signatures.items()))


def _sdk_package_exports(index_source: str) -> list[str]:
    return sorted(set(re.findall(r'export\s+\*\s+from\s+"([^"]+)"', index_source)))


def _scan_web_sdk_imports(root: Path = WEB_SRC_PATH) -> dict[str, list[str]]:
    imports: dict[str, list[str]] = {}
    if not root.exists():
        return imports
    import_pattern = re.compile(
        r"import\s+(?:type\s+)?\{(?P<body>.*?)\}\s+from\s+[\"']@focus-agent/web-sdk[\"']",
        flags=re.DOTALL,
    )
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        source = path.read_text(encoding="utf-8")
        imported_names: set[str] = set()
        for match in import_pattern.finditer(source):
            for raw_name in match.group("body").split(","):
                name = raw_name.strip()
                if not name:
                    continue
                if name.startswith("type "):
                    name = name.removeprefix("type ").strip()
                if " as " in name:
                    name = name.split(" as ", 1)[0].strip()
                if name:
                    imported_names.add(name)
        if imported_names:
            imports[str(path.relative_to(REPO_ROOT))] = sorted(imported_names)
    return imports


def build_sdk_contract() -> dict[str, Any]:
    client_source = SDK_CLIENT_PATH.read_text(encoding="utf-8")
    types_source = SDK_TYPES_PATH.read_text(encoding="utf-8")
    reducers_source = SDK_REDUCERS_PATH.read_text(encoding="utf-8")
    index_source = SDK_INDEX_PATH.read_text(encoding="utf-8")
    client_body = _class_body(client_source, "FocusAgentClient")
    method_signatures = _public_method_signatures(client_body)
    type_declarations = _scan_type_exports(types_source) | _scan_braced_exports(
        types_source,
        "interface",
    )
    reducer_events = sorted(set(re.findall(r'case\s+"([^"]+)"', reducers_source)))
    return {
        "version": 1,
        "client_methods": sorted(method_signatures),
        "client_method_signatures": method_signatures,
        "exported_types": _exported_type_names(types_source),
        "exported_type_declarations": dict(sorted(type_declarations.items())),
        "stream_event_names": _event_names(types_source),
        "reducer_event_cases": reducer_events,
        "package_exports": _sdk_package_exports(index_source),
        "web_sdk_imports": _scan_web_sdk_imports(),
    }


def _api_for_breaking_compare(contract: dict[str, Any]) -> dict[str, Any]:
    comparable = deepcopy(contract)
    for route in comparable.get("routes", []):
        if isinstance(route, dict):
            route.pop("operation_id", None)
    return comparable


def compare_api_contract(expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
    if _api_for_breaking_compare(expected) == _api_for_breaking_compare(current):
        return []
    return ["API route contract changed; run scripts/check_contracts.py --update if intentional"]


def compare_sdk_contract(expected: dict[str, Any], current: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in (
        "client_methods",
        "client_method_signatures",
        "exported_types",
        "exported_type_declarations",
        "stream_event_names",
        "reducer_event_cases",
        "package_exports",
        "web_sdk_imports",
    ):
        if expected.get(key) != current.get(key):
            failures.append(f"SDK contract changed: {key}")
    return failures


def _filter_failures(failures: Iterable[str]) -> list[str]:
    return [failure for failure in failures if failure]


def check_contracts(
    *,
    api_snapshot_path: Path = API_SNAPSHOT_PATH,
    sdk_snapshot_path: Path = SDK_SNAPSHOT_PATH,
) -> list[str]:
    current_api = build_api_contract()
    current_sdk = build_sdk_contract()
    failures = []
    failures.extend(compare_api_contract(_load_json(api_snapshot_path), current_api))
    failures.extend(compare_sdk_contract(_load_json(sdk_snapshot_path), current_sdk))
    return _filter_failures(failures)


def update_snapshots(
    *,
    api_snapshot_path: Path = API_SNAPSHOT_PATH,
    sdk_snapshot_path: Path = SDK_SNAPSHOT_PATH,
) -> None:
    _write_json(api_snapshot_path, build_api_contract())
    _write_json(sdk_snapshot_path, build_sdk_contract())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Rewrite contract snapshots")
    parser.add_argument("--api-snapshot", type=Path, default=API_SNAPSHOT_PATH)
    parser.add_argument("--sdk-snapshot", type=Path, default=SDK_SNAPSHOT_PATH)
    args = parser.parse_args(argv)

    if args.update:
        update_snapshots(api_snapshot_path=args.api_snapshot, sdk_snapshot_path=args.sdk_snapshot)
        print(f"updated {args.api_snapshot}")
        print(f"updated {args.sdk_snapshot}")
        return 0

    failures = check_contracts(
        api_snapshot_path=args.api_snapshot,
        sdk_snapshot_path=args.sdk_snapshot,
    )
    if failures:
        for failure in failures:
            print(f"[contract] {failure}", file=sys.stderr)
        return 1
    print("[contract] API and SDK contracts match snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
