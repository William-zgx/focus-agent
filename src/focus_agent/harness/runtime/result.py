"""Result type for encoding success/failure without exceptions.

Inspired by Rust's ``Result<T, E>`` discriminated union and pi-calculus
style error encoding, this module provides a small set of types that let
tool/harness methods return *either* an ``Ok(value)`` *or* an ``Err(error)``
rather than raising. Callers are forced to handle both branches explicitly
(or opt into raising with :meth:`Err.get_or_raise`), which makes failure
paths first-class and keeps async streaming pipelines from being terminated
by unexpected exceptions.

Usage::

    def divide(a: int, b: int) -> Result[float, CodedError]:
        if b == 0:
            return err(CodedError(
                code=INVALID_ARGUMENT,
                message="division by zero",
            ))
        return ok(a / b)

    outcome = divide(10, 2)
    value = outcome.get_or(0.0)                 # -> 5.0
    doubled = outcome.map(lambda x: x * 2)     # -> Ok(10.0)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar, Union

T = TypeVar("T")
U = TypeVar("U")
E = TypeVar("E")


# ---------------------------------------------------------------------------
# Common error codes
# ---------------------------------------------------------------------------

NOT_FOUND: str = "NOT_FOUND"
PERMISSION_DENIED: str = "PERMISSION_DENIED"
ALREADY_EXISTS: str = "ALREADY_EXISTS"
INVALID_ARGUMENT: str = "INVALID_ARGUMENT"
TIMED_OUT: str = "TIMED_OUT"
UNAVAILABLE: str = "UNAVAILABLE"
INTERNAL: str = "INTERNAL"


# ---------------------------------------------------------------------------
# CodedError
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodedError:
    """Structured error carrying a machine-readable code, a human message,
    and an optional free-form details dict.

    Used as the canonical ``E`` parameter for :class:`Result` types across the
    harness, so that callers can branch on :attr:`code` without parsing
    strings.
    """

    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def with_details(self, **kwargs: Any) -> CodedError:
        """Return a copy with ``details`` updated/set to ``kwargs``.

        Because the dataclass is frozen this produces a new instance; useful
        for layering contextual information onto a shared error template.
        """
        merged: dict[str, Any] = dict(self.details or {})
        merged.update(kwargs)
        return CodedError(code=self.code, message=self.message, details=merged or None)


# ---------------------------------------------------------------------------
# Ok / Err variants
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    """Success variant of :class:`Result`; wraps a value."""

    value: T
    is_ok: bool = True
    is_err: bool = False

    def map(self, fn: Callable[[T], U]) -> Ok[U]:
        """Apply ``fn`` to the contained value, returning a new ``Ok``."""
        return Ok(fn(self.value))

    def and_then(self, fn: Callable[[T], Result[U, E]]) -> Result[U, E]:
        """Apply ``fn`` (which itself returns a ``Result``) and flatten."""
        return fn(self.value)

    def get_or_raise(self) -> T:
        """Return the contained value (no-op for ``Ok``)."""
        return self.value

    def get_or(self, _default: T | U) -> T:
        """Return the contained value, ignoring ``_default``."""
        return self.value


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    """Failure variant of :class:`Result`; wraps an error."""

    error: E
    is_ok: bool = False
    is_err: bool = True

    def map(self, _fn: Callable[[Any], Any]) -> Err[E]:
        """No-op; propagates the error unchanged."""
        return self

    def and_then(self, _fn: Callable[[Any], Any]) -> Err[E]:
        """No-op; propagates the error unchanged."""
        return self

    def get_or_raise(self) -> Any:
        """Raise the contained error.

        If :attr:`error` is an :class:`Exception` instance it is raised
        directly; otherwise it is wrapped in a :class:`RuntimeError` whose
        message is ``str(error)``.
        """
        if isinstance(self.error, Exception):
            raise self.error
        raise RuntimeError(str(self.error))

    def get_or(self, default: U) -> U:
        """Return ``default``."""
        return default


# ---------------------------------------------------------------------------
# Result alias and constructors
# ---------------------------------------------------------------------------

Result = Union[Ok[T], Err[E]]
"""Discriminated union: ``Ok[T] | Err[E]``.

Use as the return type of any operation that can fail, e.g.::

    def fetch_user(uid: str) -> Result[User, CodedError]:
        ...
"""


def ok(value: T | None = None) -> Ok[T | None]:
    """Construct an :class:`Ok` result. ``value`` defaults to ``None`` for
    callers that only need to signal success without a payload."""
    return Ok(value)


def err(error: E) -> Err[E]:
    """Construct an :class:`Err` result wrapping ``error``."""
    return Err(error)


__all__ = [
    "ALREADY_EXISTS",
    "CodedError",
    "Err",
    "INTERNAL",
    "INVALID_ARGUMENT",
    "NOT_FOUND",
    "Ok",
    "PERMISSION_DENIED",
    "Result",
    "TIMED_OUT",
    "UNAVAILABLE",
    "err",
    "ok",
]
