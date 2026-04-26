from __future__ import annotations

# ruff: noqa: F403, F405
from ..route_helpers import *

def register_frontend_routes(app: FastAPI, *, settings: Settings) -> None:
    frontend_dist_dir = resolve_frontend_dist_dir(settings)
    frontend_assets_dir = frontend_dist_dir / "assets"
    frontend_dev_server_url = resolve_frontend_dev_server_url(settings)
    if frontend_dev_server_url is None and frontend_assets_dir.exists():
        app.mount("/app/assets", StaticFiles(directory=frontend_assets_dir), name="frontend_assets")
    app.include_router(create_frontend_router(settings))


def create_frontend_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    @router.get('/app', response_class=HTMLResponse)
    def render_chat_app_page(request: Request):
        redirect = _frontend_dev_redirect(settings=settings, query=request.url.query)
        if redirect is not None:
            return redirect
        return _render_frontend_or_raise(settings=settings)

    @router.get('/app/zh', response_class=HTMLResponse)
    def redirect_chinese_chat_app() -> RedirectResponse:
        redirect = _frontend_dev_redirect(settings=settings, query="lang=zh")
        if redirect is not None:
            return redirect
        return RedirectResponse(url='/app?lang=zh', status_code=307)

    @router.get('/app/{path:path}', response_class=HTMLResponse)
    def render_chat_app_subpath(path: str, request: Request):
        redirect = _frontend_dev_redirect(settings=settings, path=path, query=request.url.query)
        if redirect is not None:
            return redirect
        return _render_frontend_or_raise(settings=settings)

    return router
