import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from focus_agent.capabilities.default_tools import get_default_tools
from focus_agent.config import (
    GitLogToolConfig,
    ListFilesToolConfig,
    ReadFileToolConfig,
    SearchCodeToolConfig,
    Settings,
    ToolCatalogConfig,
    WebSearchConfig,
)


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


def test_web_search_uses_configured_api_key_env_from_settings(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)

    def fake_urlopen(request, timeout=0):
        assert request.headers["Authorization"] == "Bearer alt-key"
        return _FakeHttpResponse(
            json.dumps(
                {
                    "answer": "Configured env",
                    "results": [
                        {"title": "Configured", "url": "https://example.com/configured", "content": "ok"},
                    ],
                }
            )
        )

    monkeypatch.setattr("focus_agent.capabilities.default_tools.urllib_request.urlopen", fake_urlopen)

    tools = _tool_map(
        Settings(
            web_search=WebSearchConfig(provider="tavily", api_key_env="ALT_TAVILY_API_KEY"),
            resolved_env={"ALT_TAVILY_API_KEY": "alt-key"},
        )
    )
    payload = json.loads(tools["web_search"].invoke({"query": "configured env"}))

    assert payload["provider"] == "tavily"
    assert payload["answer"] == "Configured env"


def test_tool_metadata_uses_configured_label_and_description(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(
        Settings(
            web_search=WebSearchConfig(
                label="Live Search",
                description="Use live search with provider fallback.",
                provider="duckduckgo",
            )
        )
    )

    assert tools["web_search"].description == "Use live search with provider fallback."
    assert tools["web_search"].metadata["display_name"] == "Live Search"


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


def test_web_search_raises_when_both_providers_fail(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = []
    _FakeDDGS.raised = RuntimeError("ddg down")
    tools = _tool_map(Settings())

    with pytest.raises(RuntimeError, match="DuckDuckGo error"):
        tools["web_search"].invoke({"query": "hello"})


def test_default_tools_expose_only_one_web_search_tool(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(Settings())

    assert "web_search" in tools
    assert "tavily_search" not in tools
    assert "list_files" in tools
    assert "read_file" in tools
    assert "search_code" in tools
    assert "codebase_stats" in tools
    assert "git_status" in tools
    assert "git_diff" in tools
    assert "git_log" in tools


def test_disabled_tools_are_removed_from_registry(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(
        Settings(
            tool_catalog=ToolCatalogConfig(
                list_files=ListFilesToolConfig(enabled=False),
                git_log=GitLogToolConfig(enabled=False),
            ),
            web_search=WebSearchConfig(provider="duckduckgo"),
        )
    )

    assert "list_files" not in tools
    assert "git_log" not in tools
    assert "read_file" in tools
    assert "web_search" in tools


def test_web_search_respects_duckduckgo_only_configuration(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = [
        {"title": "DDG only", "href": "https://example.com/ddg-only", "body": "fallback content"},
    ]
    _FakeDDGS.raised = None

    def unexpected_urlopen(_request, timeout=0):
        raise AssertionError("Tavily should not be called when provider=duckduckgo")

    monkeypatch.setattr("focus_agent.capabilities.default_tools.urllib_request.urlopen", unexpected_urlopen)

    tools = _tool_map(Settings(web_search=WebSearchConfig(provider="duckduckgo")))
    payload = json.loads(tools["web_search"].invoke({"query": "hello"}))

    assert payload["provider"] == "duckduckgo"
    assert payload["results"][0]["title"] == "DDG only"


def test_web_search_respects_disabled_configuration(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)

    tools = _tool_map(Settings(web_search=WebSearchConfig(enabled=False)))

    assert "web_search" not in tools


def test_write_text_artifact_defaults_to_local_focus_agent_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            artifact_dir=str(project / ".focus_agent" / "artifacts"),
        )
    )

    result = str(tools["write_text_artifact"].invoke({"title": "AI Notes", "body": "Local only"}))

    expected_path = project / ".focus_agent" / "artifacts" / "ai-notes.md"
    assert result == f"artifact_saved:{expected_path}"
    assert expected_path.read_text(encoding="utf-8") == "# AI Notes\n\nLocal only\n"


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


def test_list_files_uses_configured_default_max_results(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    for index in range(5):
        (project / f"file-{index}.txt").write_text("demo\n", encoding="utf-8")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                list_files=ListFilesToolConfig(default_max_results=2, max_results_cap=4)
            ),
        )
    )

    payload = json.loads(tools["list_files"].invoke({"path": "."}))

    assert len(payload["results"]) == 2
    assert payload["truncated"] is True


def test_read_file_uses_configured_default_end_line(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "notes.txt"
    sample.write_text("a\nb\nc\nd\n", encoding="utf-8")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                read_file=ReadFileToolConfig(default_end_line=2, max_lines=2, max_chars=1000)
            ),
        )
    )

    payload = json.loads(tools["read_file"].invoke({"path": "notes.txt"}))

    assert payload["end_line"] == 2
    assert "3 |" not in payload["content"]


def test_search_code_uses_configured_default_max_results(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "sample.py"
    sample.write_text("match()\nmatch()\nmatch()\n", encoding="utf-8")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                search_code=SearchCodeToolConfig(default_max_results=2, max_results_cap=3)
            ),
        )
    )

    payload = json.loads(tools["search_code"].invoke({"query": "match", "literal": True}))

    assert len(payload["results"]) == 2
    assert payload["truncated"] is True
    assert all(item["path"] == "sample.py" for item in payload["results"])


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
