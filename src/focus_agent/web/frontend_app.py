from __future__ import annotations

from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit

from ..config import Settings


def default_frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"


def resolve_frontend_dist_dir(settings: Settings | None = None) -> Path:
    configured = getattr(settings, "web_app_dist_dir", None) if settings is not None else None
    if configured:
        return Path(configured).expanduser().resolve()
    return default_frontend_dist_dir().resolve()


def resolve_frontend_dev_server_url(settings: Settings | None = None) -> str | None:
    configured = getattr(settings, "web_app_dev_server_url", None) if settings is not None else None
    if not configured:
        return None
    normalized = str(configured).strip().rstrip("/")
    return normalized or None


def build_frontend_dev_server_redirect_url(
    *,
    settings: Settings | None = None,
    path: str = "",
    query: str = "",
) -> str | None:
    base_url = resolve_frontend_dev_server_url(settings)
    if base_url is None:
        return None

    parsed = urlsplit(base_url)
    suffix = str(path).lstrip("/")
    base_path = parsed.path.rstrip("/")
    next_path = f"{base_path}/" if not suffix and base_path else base_path
    if suffix:
        next_path = f"{base_path}/{suffix}"
    next_query = query or parsed.query
    return urlunsplit(
        SplitResult(
            scheme=parsed.scheme,
            netloc=parsed.netloc,
            path=next_path or "/",
            query=next_query,
            fragment="",
        )
    )


def has_frontend_build(settings: Settings | None = None) -> bool:
    dist_dir = resolve_frontend_dist_dir(settings)
    return (dist_dir / "index.html").exists()


def render_frontend_entry_html(*, settings: Settings | None = None) -> str:
    dist_dir = resolve_frontend_dist_dir(settings)
    index_path = dist_dir / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Frontend build is missing: {index_path}")
