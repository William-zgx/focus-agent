from pathlib import Path

import pytest

from focus_agent.config import Settings
from focus_agent.web.frontend_app import (
    build_frontend_dev_server_redirect_url,
    has_frontend_build,
    render_frontend_entry_html,
    resolve_frontend_dev_server_url,
)


def test_render_frontend_entry_html_raises_when_build_is_missing(tmp_path: Path):
    settings = Settings.from_env()
    settings.web_app_dist_dir = str(tmp_path / "missing-dist")

    with pytest.raises(FileNotFoundError):
        render_frontend_entry_html(settings=settings)

    assert has_frontend_build(settings) is False


def test_render_frontend_entry_html_reads_built_index_when_present(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<!doctype html><html><body>react-app</body></html>", encoding="utf-8")

    settings = Settings.from_env()
    settings.web_app_dist_dir = str(dist_dir)

    html = render_frontend_entry_html(settings=settings)

    assert "react-app" in html
    assert has_frontend_build(settings) is True


def test_resolve_frontend_dev_server_url_normalizes_trailing_slash():
    settings = Settings.from_env()
    settings.web_app_dev_server_url = "http://127.0.0.1:5173/app/"

    assert resolve_frontend_dev_server_url(settings) == "http://127.0.0.1:5173/app"


def test_build_frontend_dev_server_redirect_url_preserves_path_and_query():
    settings = Settings.from_env()
    settings.web_app_dev_server_url = "http://127.0.0.1:5173/app/"

    target = build_frontend_dev_server_redirect_url(
        settings=settings,
        path="c/demo/t/demo",
        query="lang=zh",
    )

    assert target == "http://127.0.0.1:5173/app/c/demo/t/demo?lang=zh"


def test_build_frontend_dev_server_redirect_url_keeps_app_root_slash():
    settings = Settings.from_env()
    settings.web_app_dev_server_url = "http://127.0.0.1:5173/app/"

    target = build_frontend_dev_server_redirect_url(settings=settings)

    assert target == "http://127.0.0.1:5173/app/"
