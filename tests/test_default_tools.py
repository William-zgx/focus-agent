import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from focus_agent.capabilities.default_tools import get_default_tools
from focus_agent.config import Settings


class _FakeHttpResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDDGS:
    results = []
    raised = None
    last_query = None
    last_max_results = None

    def __init__(self, timeout=30):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, query, region="wt-wt", safesearch="moderate", max_results=5):
        _FakeDDGS.last_query = query
        _FakeDDGS.last_max_results = max_results
        if _FakeDDGS.raised is not None:
            raise _FakeDDGS.raised
        return list(_FakeDDGS.results)


def _install_fake_ddgs(monkeypatch):
    fake_module = types.ModuleType("ddgs")
    fake_module.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_module)


def _tool_map(settings: Settings) -> dict[str, object]:
    return {tool.name: tool for tool in get_default_tools(settings)}


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Focus Agent"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "focus-agent@example.com"], cwd=path, check=True, capture_output=True)


def test_web_search_prefers_tavily_when_available(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _install_fake_ddgs(monkeypatch)

    def fake_urlopen(request, timeout=0):
        assert request.full_url == "https://api.tavily.com/search"
        assert timeout == 30
        body = json.loads(request.data.decode("utf-8"))
        assert body["query"] == "latest model release"
        assert body["max_results"] == 3
        return _FakeHttpResponse(
            json.dumps(
                {
                    "answer": "A concise answer",
                    "results": [
                        {"title": "Official docs", "url": "https://example.com/docs", "content": "doc"},
                        {"title": "Release notes", "url": "https://example.com/release", "content": "notes"},
                    ],
                }
            )
        )

    monkeypatch.setattr("focus_agent.capabilities.default_tools.urllib_request.urlopen", fake_urlopen)

    tools = _tool_map(Settings())
    payload = json.loads(tools["web_search"].invoke({"query": "latest model release", "max_results": 3}))

    assert payload["query"] == "latest model release"
    assert payload["provider"] == "tavily"
    assert payload["answer"] == "A concise answer"
    assert payload["results"][0]["title"] == "Official docs"


def test_web_search_falls_back_to_duckduckgo_when_tavily_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = [
        {"title": "DDG result", "href": "https://example.com/ddg", "body": "fallback content"},
    ]
    _FakeDDGS.raised = None
    tools = _tool_map(Settings())

    payload = json.loads(tools["web_search"].invoke({"query": "hello", "max_results": 4}))

    assert payload["provider"] == "duckduckgo"
    assert payload["answer"] is None
    assert payload["results"][0]["url"] == "https://example.com/ddg"
    assert _FakeDDGS.last_query == "hello"
    assert _FakeDDGS.last_max_results == 4


def test_web_search_falls_back_to_duckduckgo_when_tavily_fails(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = [
        {"title": "Fallback", "link": "https://example.com/fallback", "snippet": "backup"},
    ]
    _FakeDDGS.raised = None

    def failing_urlopen(_request, timeout=0):
        raise OSError("dns failed")

    monkeypatch.setattr("focus_agent.capabilities.default_tools.urllib_request.urlopen", failing_urlopen)
    tools = _tool_map(Settings())

    payload = json.loads(tools["web_search"].invoke({"query": "hello"}))

    assert payload["provider"] == "duckduckgo"
    assert payload["results"][0]["title"] == "Fallback"


def test_tavily_search_alias_matches_web_search(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = [
        {"title": "Alias", "href": "https://example.com/alias", "body": "same shape"},
    ]
    _FakeDDGS.raised = None
    tools = _tool_map(Settings())

    web_payload = json.loads(tools["web_search"].invoke({"query": "compat"}))
    alias_payload = json.loads(tools["tavily_search"].invoke({"query": "compat"}))

    assert web_payload == alias_payload


def test_web_search_raises_when_both_providers_fail(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = []
    _FakeDDGS.raised = RuntimeError("ddg down")
    tools = _tool_map(Settings())

    with pytest.raises(RuntimeError, match="DuckDuckGo error"):
        tools["web_search"].invoke({"query": "hello"})


def test_default_tools_include_web_search_and_tavily_alias(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(Settings())

    assert "web_search" in tools
    assert "tavily_search" in tools
    assert "list_files" in tools
    assert "read_file" in tools
    assert "search_code" in tools
    assert "codebase_stats" in tools
    assert "git_status" in tools
    assert "git_diff" in tools
    assert "git_log" in tools


def test_read_file_and_search_code_stay_within_workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "src" / "app.py"
    sample.parent.mkdir()
    sample.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    read_payload = json.loads(
        tools["read_file"].invoke(
            {"path": "src/app.py", "start_line": 1, "end_line": 5}
        )
    )
    search_payload = json.loads(
        tools["search_code"].invoke(
            {"query": "greet", "path": ".", "glob": "**/*.py", "literal": True}
        )
    )

    assert read_payload["path"] == "src/app.py"
    assert "1 | def greet()" in read_payload["content"]
    assert search_payload["results"][0]["path"] == "src/app.py"
    assert search_payload["results"][0]["line_number"] == 1

    with pytest.raises(ValueError, match="workspace root"):
        tools["read_file"].invoke({"path": "../outside.txt"})


def test_list_files_and_codebase_stats_filter_common_dependency_dirs(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "node_modules").mkdir()
    (project / ".git").mkdir()
    (project / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (project / "node_modules" / "leftpad.js").write_text("module.exports = 1;\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    list_payload = json.loads(tools["list_files"].invoke({"path": ".", "pattern": "**/*"}))
    stats_payload = json.loads(tools["codebase_stats"].invoke({"path": "."}))

    assert list_payload["results"] == ["src/main.py"]
    assert stats_payload["files_scanned"] == 1
    assert stats_payload["language_breakdown"][0]["language"] == "Python"


def test_list_files_default_glob_includes_workspace_root_files(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text("# demo\n", encoding="utf-8")
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(tools["list_files"].invoke({"path": ".", "pattern": "**/*"}))

    assert "README.md" in payload["results"]
    assert "src/main.py" in payload["results"]


def test_search_code_glob_matches_root_level_files_with_double_star(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (project / "pkg").mkdir()
    (project / "pkg" / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(
        tools["search_code"].invoke(
            {"query": "VALUE", "path": ".", "glob": "**/*.py", "literal": True, "max_results": 10}
        )
    )

    matched_paths = [item["path"] for item in payload["results"]]
    assert "main.py" in matched_paths
    assert "pkg/module.py" in matched_paths


def test_git_tools_return_status_diff_and_log(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    _init_git_repo(project)
    tracked = project / "tracked.txt"
    tracked.write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=project, check=True, capture_output=True)
    tracked.write_text("hello\nworld\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    status_payload = json.loads(tools["git_status"].invoke({}))
    diff_payload = json.loads(tools["git_diff"].invoke({"pathspec": "tracked.txt"}))
    log_payload = json.loads(tools["git_log"].invoke({"limit": 5}))

    assert status_payload["branch"] is not None
    assert any("tracked.txt" in entry for entry in status_payload["entries"])
    assert "+world" in diff_payload["diff"]
    assert log_payload["commits"][0]["subject"] == "initial"
