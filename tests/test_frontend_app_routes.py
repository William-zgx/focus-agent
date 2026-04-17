from pathlib import Path

from fastapi.testclient import TestClient

from focus_agent.api.main import create_app


def test_app_route_falls_back_to_legacy_shell_when_no_build(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEB_APP_DIST_DIR", str(tmp_path / "missing-dist"))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    app = create_app()
    client = TestClient(app)

    response = client.get("/app")

    assert response.status_code == 503
    assert "Frontend build is missing" in response.text


def test_app_route_serves_built_index_and_supports_spa_subpaths(monkeypatch, tmp_path: Path):
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>react-app</div></body></html>",
        encoding="utf-8",
    )
    (assets_dir / "main.js").write_text("console.log('ok')", encoding="utf-8")

    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "")
    app = create_app()
    client = TestClient(app)

    app_response = client.get("/app")
    review_response = client.get("/app/c/demo/t/demo/review")
    asset_response = client.get("/app/assets/main.js")

    assert app_response.status_code == 200
    assert "react-app" in app_response.text
    assert review_response.status_code == 200
    assert "react-app" in review_response.text
    assert asset_response.status_code == 200
    assert "console.log('ok')" in asset_response.text


def test_app_route_redirects_to_vite_dev_server_when_configured(monkeypatch, tmp_path: Path):
    dist_dir = tmp_path / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><body><div id='root'>built-app</div></body></html>",
        encoding="utf-8",
    )
    (assets_dir / "main.js").write_text("console.log('built')", encoding="utf-8")

    monkeypatch.setenv("WEB_APP_DIST_DIR", str(dist_dir))
    monkeypatch.setenv("WEB_APP_DEV_SERVER_URL", "http://127.0.0.1:5173/app/")
    app = create_app()
    client = TestClient(app)

    app_response = client.get("/app/c/demo/t/demo?lang=zh", follow_redirects=False)
    asset_response = client.get("/app/assets/main.js", follow_redirects=False)

    assert app_response.status_code == 307
    assert app_response.headers["location"] == "http://127.0.0.1:5173/app/c/demo/t/demo?lang=zh"
    assert asset_response.status_code == 307
    assert asset_response.headers["location"] == "http://127.0.0.1:5173/app/assets/main.js"
