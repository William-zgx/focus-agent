from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import RedirectResponse

from focus_agent.config import Settings
from focus_agent.web.frontend_app import (
    build_frontend_dev_server_redirect_url,
    render_frontend_entry_html,
)


def _render_frontend_or_raise(*, settings: Settings) -> str:
    try:
        return render_frontend_entry_html(settings=settings)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Frontend build is missing. Run `pnpm web:build` or `make web-build` "
                "before opening /app."
            ),
        ) from exc


def _frontend_dev_redirect(
    *,
    settings: Settings,
    path: str = "",
    query: str = "",
) -> RedirectResponse | None:
    target = build_frontend_dev_server_redirect_url(settings=settings, path=path, query=query)
    if target is None:
        return None
    return RedirectResponse(url=target, status_code=307)




__all__ = [
    "_frontend_dev_redirect",
    "_render_frontend_or_raise",
]
