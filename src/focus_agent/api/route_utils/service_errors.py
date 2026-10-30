"""Translate service-layer exceptions raised inside route handlers into HTTP errors."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import NoReturn

from fastapi import HTTPException

from focus_agent.services.chat.errors import ConcurrentTurnError

logger = logging.getLogger("focus_agent.api")

ExceptionTypes = type[BaseException] | tuple[type[BaseException], ...]
ErrorHandler = int | Callable[[Exception], NoReturn]
ErrorRule = tuple[ExceptionTypes, ErrorHandler]

PERMISSION_ERROR_RULE: ErrorRule = (PermissionError, 403)
CONCURRENT_TURN_ERROR_RULE: ErrorRule = (ConcurrentTurnError, 409)
NOT_FOUND_ERROR_RULE: ErrorRule = (KeyError, 404)
BAD_REQUEST_ERROR_RULE: ErrorRule = (ValueError, 400)

SERVICE_ERROR_RULES: tuple[ErrorRule, ...] = (
    PERMISSION_ERROR_RULE,
    CONCURRENT_TURN_ERROR_RULE,
    NOT_FOUND_ERROR_RULE,
    BAD_REQUEST_ERROR_RULE,
)

INTERNAL_ERROR_DETAIL = "Internal server error."


@contextmanager
def map_service_errors(
    *overrides: ErrorRule,
    rules: Sequence[ErrorRule] = SERVICE_ERROR_RULES,
    unexpected_as_500: bool = False,
) -> Iterator[None]:
    """Map exceptions to ``HTTPException`` using the first matching rule.

    ``overrides`` are checked before ``rules``. A rule's handler is either an HTTP
    status code (the exception text becomes the detail) or a callable that raises.
    Unmatched exceptions propagate unless ``unexpected_as_500`` is set, in which case
    they are logged and reported as a generic 500 without leaking internals.
    """
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:
        for exc_types, handler in (*overrides, *rules):
            if not isinstance(exc, exc_types):
                continue
            if isinstance(handler, int):
                raise HTTPException(status_code=handler, detail=str(exc)) from exc
            handler(exc)
            raise
        if unexpected_as_500:
            logger.exception("unexpected_route_service_error")
            raise HTTPException(status_code=500, detail=INTERNAL_ERROR_DETAIL) from exc
        raise


__all__ = [
    "BAD_REQUEST_ERROR_RULE",
    "CONCURRENT_TURN_ERROR_RULE",
    "INTERNAL_ERROR_DETAIL",
    "NOT_FOUND_ERROR_RULE",
    "PERMISSION_ERROR_RULE",
    "SERVICE_ERROR_RULES",
    "ErrorRule",
    "map_service_errors",
]
