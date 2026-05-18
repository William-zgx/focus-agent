from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Iterable, Mapping
from dataclasses import MISSING, Field, asdict, fields, is_dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel


def tool_schema_fingerprint(
    tool_or_schema: Any,
    *,
    digest_size: int | None = None,
) -> str:
    """Return a stable SHA-256 fingerprint for a tool object or schema payload."""

    return _digest_payload(canonical_tool_schema(tool_or_schema), digest_size=digest_size)


def tools_schema_fingerprint(
    tools: Iterable[Any],
    *,
    digest_size: int | None = None,
) -> str:
    """Return a stable SHA-256 fingerprint for a collection of tool schemas."""

    payload = [
        {
            "name": str(getattr(tool, "name", "") or ""),
            "schema": canonical_tool_schema(tool),
        }
        for tool in tools
    ]
    payload.sort(key=lambda item: (item["name"], json.dumps(item["schema"], sort_keys=True)))
    return _digest_payload(payload, digest_size=digest_size)


def _digest_payload(payload: Any, *, digest_size: int | None) -> str:
    if digest_size is not None and digest_size <= 0:
        raise ValueError("digest_size must be positive when provided.")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return digest[:digest_size] if digest_size is not None else digest


def canonical_tool_schema(tool_or_schema: Any) -> Any:
    """Normalize tool schema data into a JSON-compatible canonical payload."""

    return _json_safe(_tool_schema_payload(tool_or_schema))


def _tool_schema_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, list | tuple):
        return value
    if _is_pydantic_model_type(value):
        return value.model_json_schema()
    if _is_tool_like(value):
        return _tool_payload(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        if isinstance(value, type):
            return {
                "dataclass": f"{value.__module__}.{value.__qualname__}",
                "fields": [_dataclass_field_payload(field) for field in fields(value)],
            }
        return asdict(value)
    if callable(value):
        return _callable_payload(value)
    return value


def _tool_payload(tool_obj: Any) -> dict[str, Any]:
    return {
        "name": str(getattr(tool_obj, "name", "") or ""),
        "description": str(getattr(tool_obj, "description", "") or ""),
        "input_schema": _input_schema_for_tool(tool_obj),
    }


def _input_schema_for_tool(tool_obj: Any) -> Any:
    args_schema = getattr(tool_obj, "args_schema", None)
    if args_schema is not None:
        return _schema_payload_from_object(args_schema)

    get_input_schema = getattr(tool_obj, "get_input_schema", None)
    if callable(get_input_schema):
        try:
            return _schema_payload_from_object(get_input_schema())
        except TypeError:
            pass

    tool_call_schema = getattr(tool_obj, "tool_call_schema", None)
    if tool_call_schema is not None:
        schema_obj = tool_call_schema
        if callable(tool_call_schema) and not _is_pydantic_model_type(tool_call_schema):
            try:
                schema_obj = tool_call_schema()
            except TypeError:
                schema_obj = tool_call_schema
        return _schema_payload_from_object(schema_obj)

    args = getattr(tool_obj, "args", None)
    if isinstance(args, Mapping):
        return args

    return _callable_payload(tool_obj) if callable(tool_obj) else {}


def _schema_payload_from_object(value: Any) -> Any:
    if isinstance(value, Mapping):
        return value
    if _is_pydantic_model_type(value):
        return value.model_json_schema()
    model_json_schema = getattr(value, "model_json_schema", None)
    if callable(model_json_schema):
        return model_json_schema()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def _callable_payload(value: Any) -> dict[str, Any]:
    payload = {
        "callable": f"{getattr(value, '__module__', '')}.{getattr(value, '__qualname__', '')}",
        "name": str(getattr(value, "__name__", "") or getattr(value, "name", "") or ""),
        "doc": str(inspect.getdoc(value) or ""),
    }
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return payload
    payload["parameters"] = {
        name: {
            "kind": parameter.kind.name,
            "annotation": _annotation_repr(parameter.annotation),
            "default": None
            if parameter.default is inspect.Parameter.empty
            else _json_safe(parameter.default),
        }
        for name, parameter in signature.parameters.items()
    }
    payload["return_annotation"] = _annotation_repr(signature.return_annotation)
    return payload


def _dataclass_field_payload(field: Field[Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": field.name,
        "type": _annotation_repr(field.type),
    }
    if field.default is not MISSING:
        payload["default"] = _json_safe(field.default)
    elif field.default_factory is not MISSING:
        payload["default_factory"] = _annotation_repr(field.default_factory)
    else:
        payload["required"] = True
    return payload


def _is_tool_like(value: Any) -> bool:
    if isinstance(value, Mapping):
        return False
    if not str(getattr(value, "name", "") or "").strip():
        return False
    return any(
        hasattr(value, attr)
        for attr in ("args", "args_schema", "get_input_schema", "tool_call_schema")
    )


def _is_pydantic_model_type(value: Any) -> bool:
    try:
        return isinstance(value, type) and issubclass(value, BaseModel)
    except TypeError:
        return False


def _annotation_repr(value: Any) -> str | None:
    if value in (inspect.Parameter.empty, inspect.Signature.empty):
        return None
    module = getattr(value, "__module__", "")
    qualname = getattr(value, "__qualname__", "")
    if module and qualname:
        return f"{module}.{qualname}"
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if _is_pydantic_model_type(value):
        return _json_safe(value.model_json_schema())
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return str(value)
