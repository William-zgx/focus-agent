"""Memory and context probe release-health signals."""

from __future__ import annotations

from collections.abc import Iterable

from focus_agent.observability.release_health_models import FAIL, PASS, ReleaseHealthSignal


def evaluate_context_probe(
    rendered_context: str,
    *,
    required_markers: Iterable[str] = (),
    forbidden_markers: Iterable[str] = (),
    max_chars: int | None = None,
    key: str = "memory_context_probe",
) -> ReleaseHealthSignal:
    text = str(rendered_context or "")
    missing = [marker for marker in required_markers if marker not in text]
    forbidden = [marker for marker in forbidden_markers if marker in text]
    too_large = max_chars is not None and len(text) > max_chars
    details = {
        "chars": len(text),
        "missing": missing,
        "forbidden": forbidden,
        "max_chars": max_chars,
    }
    if missing or forbidden or too_large:
        return ReleaseHealthSignal(
            key=key,
            status=FAIL,
            summary="memory/context probe failed",
            details=details,
        )
    return ReleaseHealthSignal(
        key=key,
        status=PASS,
        summary="memory/context probe passed",
        details=details,
    )
