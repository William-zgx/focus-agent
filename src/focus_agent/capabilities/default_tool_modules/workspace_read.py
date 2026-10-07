from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain.tools import tool

from .common import _coerce_relative_posix, _read_text_file, _require_non_empty_text_arg
from .workspace_paths import _resolve_workspace_path


def _validate_read_file_args(args: dict[str, Any]) -> None:
    _require_non_empty_text_arg(args, "path")
    start_line = int(args.get("start_line", 1))
    if start_line < 1:
        raise ValueError("start_line must be at least 1.")
    end_line = args.get("end_line")
    if end_line is not None and int(end_line) < start_line:
        raise ValueError("end_line must be greater than or equal to start_line.")
    char_offset = args.get("char_offset", 0)
    if isinstance(char_offset, bool) or int(char_offset) != char_offset or int(char_offset) < 0:
        raise ValueError("char_offset must be a non-negative integer.")


def build_read_file_tool(
    *,
    workspace_root: Path,
    tool_catalog: Any,
    emit_tool_event: Callable[..., None],
) -> Any:
    @tool
    def read_file(
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
        char_offset: int = 0,
    ) -> str:
        """Read a bounded UTF-8 text file range with line numbers."""
        tool_name = "read_file"
        emit_tool_event(
            tool_name=tool_name,
            stage="start",
            path=path,
            start_line=start_line,
            end_line=end_line,
            char_offset=char_offset,
        )
        try:
            resolved = _resolve_workspace_path(raw_path=path, workspace_root=workspace_root)
            if resolved.is_dir():
                raise IsADirectoryError(path)
            if start_line < 1:
                raise ValueError("start_line must be at least 1.")
            if isinstance(char_offset, bool) or char_offset < 0:
                raise ValueError("char_offset must be a non-negative integer.")
            char_offset = int(char_offset)
            requested_end_line = (
                start_line + max(1, int(tool_catalog.read_file.default_end_line)) - 1
                if end_line is None
                else int(end_line)
            )
            if requested_end_line < start_line:
                raise ValueError("end_line must be greater than or equal to start_line.")
            max_lines = max(1, int(tool_catalog.read_file.max_lines))
            capped_end_line = min(requested_end_line, start_line + max_lines - 1)
            content = _read_text_file(resolved)
            all_lines = content.splitlines()
            available_end_line = min(capped_end_line, len(all_lines))
            number_width = max(len(str(capped_end_line)), 2)
            max_chars = max(1, int(tool_catalog.read_file.max_chars))
            source_lines: list[tuple[int, str, int]] = []
            for line_number in range(start_line, available_end_line + 1):
                line = all_lines[line_number - 1]
                line_offset = char_offset if line_number == start_line else 0
                if line_offset >= len(line) and line_number == start_line and line:
                    continue
                source_lines.append((line_number, line, line_offset))

            use_line_prefix = bool(source_lines) and max_chars > len(
                f"{source_lines[0][0]:{number_width}d} | "
            )
            fragments: list[tuple[int, int, int, str]] = []
            for line_number, line, line_offset in source_lines:
                prefix = f"{line_number:{number_width}d} | " if use_line_prefix else ""
                fragments.append(
                    (line_number, line_offset, len(prefix), prefix + line[line_offset:])
                )
            full_rendered = "\n".join(fragment[-1] for fragment in fragments)
            rendered = full_rendered[:max_chars]

            next_start_line: int | None = None
            next_char_offset: int | None = None
            end_line_value = available_end_line if source_lines else start_line - 1
            if len(full_rendered) > max_chars and fragments:
                cursor = 0
                cut_position = len(rendered)
                for index, (line_number, line_offset, prefix_length, fragment) in enumerate(
                    fragments
                ):
                    fragment_start = cursor
                    fragment_end = fragment_start + len(fragment)
                    if cut_position < fragment_end:
                        end_line_value = line_number
                        local_offset = max(0, cut_position - fragment_start)
                        if local_offset == 0:
                            end_line_value = line_number - 1
                        if local_offset < prefix_length:
                            next_char_offset = line_offset
                        else:
                            next_char_offset = line_offset + min(
                                len(fragment) - prefix_length,
                                local_offset - prefix_length,
                            )
                        next_start_line = line_number
                        break
                    if cut_position == fragment_end:
                        end_line_value = line_number
                        if index + 1 < len(fragments):
                            next_start_line = fragments[index + 1][0]
                            next_char_offset = fragments[index + 1][1]
                        break
                    cursor = fragment_end + (1 if index < len(fragments) - 1 else 0)
            elif (
                available_end_line < requested_end_line
                and available_end_line < len(all_lines)
                and available_end_line >= start_line
            ):
                next_start_line = available_end_line + 1
                next_char_offset = 0

            continuation = None
            if next_start_line is not None:
                continuation = {
                    "path": _coerce_relative_posix(resolved, workspace_root),
                    "start_line": next_start_line,
                    "end_line": requested_end_line,
                    "char_offset": next_char_offset or 0,
                }
            payload = {
                "path": _coerce_relative_posix(resolved, workspace_root),
                "start_line": start_line,
                "end_line": end_line_value,
                "total_lines": len(all_lines),
                "content": rendered,
                "char_offset": char_offset,
                "content_chars": len(rendered),
                "truncated": continuation is not None,
                "next_start_line": next_start_line,
                "next_end_line": continuation["end_line"] if continuation else None,
                "next_char_offset": next_char_offset,
                "continuation": continuation,
            }
            result = json.dumps(payload, ensure_ascii=False)
            emit_tool_event(tool_name=tool_name, stage="end", output=result[:800])
            return result
        except Exception as exc:  # noqa: BLE001
            emit_tool_event(tool_name=tool_name, stage="error", error=str(exc), path=path)
            raise

    return read_file
