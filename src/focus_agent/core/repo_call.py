from __future__ import annotations

from typing import Any

REPO_METHOD_MISSING: Any = object()
REPO_METHOD_ERROR: Any = object()


def has_repo_method(repo: Any, method_name: str) -> bool:
    """Return True when repo exposes a callable method with the given name."""

    method = getattr(repo, method_name, None)
    return callable(method)


def safe_repo_call(
    repo: Any,
    method_name: str,
    *args: Any,
    default_missing: Any = REPO_METHOD_MISSING,
    default_error: Any = REPO_METHOD_ERROR,
    fallback_args: tuple[Any, ...] | None = None,
    except_errors: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> Any:
    """Call a repo method safely, returning explicit fallback values on misses/errors."""

    method = getattr(repo, method_name, None)
    if not callable(method):
        return default_missing
    try:
        return method(*args, **kwargs)
    except TypeError as exc:
        if fallback_args is not None:
            try:
                return method(*fallback_args)
            except except_errors:
                return default_error
        if isinstance(exc, except_errors):
            return default_error
        raise
    except except_errors:
        return default_error
