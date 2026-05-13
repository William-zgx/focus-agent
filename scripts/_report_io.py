"""Small JSON/report I/O helpers shared by release scripts and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def resolve_path(path: str | Path, root: Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    return target


def resolve_optional_path(path: str | Path | None, root: Path) -> Path | None:
    if path is None:
        return None
    return resolve_path(path, root)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: str | Path) -> list[Any]:
    records: list[Any] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            records.append(json.loads(stripped))
    return records


def write_json_report(
    path: str | Path,
    payload: object,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
    sort_keys: bool = True,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=ensure_ascii, indent=indent, sort_keys=sort_keys)
    if indent is not None:
        body += "\n"
    target.write_text(body, encoding="utf-8")
    return target


def write_jsonl(path: str | Path, records: list[object]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    target.write_text(body, encoding="utf-8")
    return target


def print_json_stdout(payload: object, *, sort_keys: bool = False) -> None:
    print(json.dumps(payload, indent=2, sort_keys=sort_keys))
