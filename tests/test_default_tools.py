import json
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

from langchain.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
import pytest

from focus_agent.capabilities.default_tools import get_default_tools
from focus_agent.capabilities.tool_runtime import ToolExecutionInput, execute_tool_calls
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.config import (
    GitLogToolConfig,
    ListFilesToolConfig,
    ReadFileToolConfig,
    SearchCodeToolConfig,
    Settings,
    ToolCatalogConfig,
    WebSearchConfig,
)
from focus_agent.core.types import ContextBudget
from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore


class _FakeHeaders(dict):
    def get_content_charset(self):
        content_type = self.get("content-type", "")
        marker = "charset="
        if marker not in content_type:
            return None
        return content_type.split(marker, 1)[1].split(";", 1)[0].strip()


class _FakeHttpResponse:
    def __init__(self, body: str, *, url: str = "https://example.com/", content_type: str = "application/json"):
        self._body = body.encode("utf-8")
        self._url = url
        self.headers = _FakeHeaders({"content-type": content_type})

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url

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


class _FakeArtifactMetadataRepository:
    def __init__(self):
        self.upsert_calls: list[dict[str, object]] = []
        self.records_by_id: dict[str, types.SimpleNamespace] = {}

    def upsert_from_file(self, *, thread_id: str, artifact_id: str, path: str | Path, title: str):
        file_path = Path(path)
        stat = file_path.stat()
        previous = self.records_by_id.get(artifact_id)
        record = types.SimpleNamespace(
            artifact_id=artifact_id,
            thread_id=thread_id,
            path=str(path),
            title=title,
            size_bytes=stat.st_size,
            created_at=previous.created_at if previous is not None else datetime.now(timezone.utc),
            updated_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        )
        self.records_by_id[artifact_id] = record
        self.upsert_calls.append(
            {
                "thread_id": thread_id,
                "artifact_id": artifact_id,
                "path": str(path),
                "title": title,
            }
        )
        return record

    def list_by_thread(self, thread_id: str, *, limit: int | None = None):
        records = [
            record
            for record in self.records_by_id.values()
            if record.thread_id == thread_id
        ]
        records.sort(key=lambda record: (-record.updated_at.timestamp(), record.artifact_id))
        if limit is not None:
            return records[:limit]
        return records

    def get_by_artifact_id(self, artifact_id: str):
        return self.records_by_id.get(artifact_id)


class _MemoryToolStore:
    def __init__(self, search_results_by_namespace: dict[tuple[str, ...], list[object]] | None = None):
        self.data: dict[tuple[str, ...], dict[str, dict[str, object]]] = {}
        self.search_results_by_namespace = {
            tuple(namespace): list(results)
            for namespace, results in (search_results_by_namespace or {}).items()
        }

    def put(self, namespace, key, value):
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)

    def get(self, namespace, key):
        return self.data.get(tuple(namespace), {}).get(key)

    def delete(self, namespace, key):
        self.data.get(tuple(namespace), {}).pop(key, None)

    def search(self, namespace, query, limit):  # noqa: ARG002
        namespace_key = tuple(namespace)
        predefined = self.search_results_by_namespace.get(namespace_key)
        if predefined is not None:
            return predefined[:limit]
        return [
            types.SimpleNamespace(
                key=memory_id,
                namespace=namespace_key,
                score=0.5,
                value=payload,
            )
            for memory_id, payload in self.data.get(namespace_key, {}).items()
        ][:limit]


def _tool_map(settings: Settings, *, artifact_metadata_repository=None) -> dict[str, object]:
    return {
        tool.name: tool
        for tool in get_default_tools(
            settings,
            artifact_metadata_repository=artifact_metadata_repository,
        )
    }


def _runtime_invoke(tool_obj, args: dict[str, object]) -> tuple[str, str]:
    result = execute_tool_calls(
        [
            ToolExecutionInput(
                index=0,
                tool_call_id="tool-call-1",
                tool_name=tool_obj.name,
                args=dict(args),
                tool=tool_obj,
                runtime=ToolRuntimeMeta.from_tool(tool_obj),
            )
        ],
        context_budget=ContextBudget(),
        cache_store={},
        cache_scope_keys={0: "thread:test"},
    )[0]
    return result.message.status, str(result.message.content)


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


def test_tool_runtime_metadata_marks_parallel_cacheable_and_fallback_capabilities(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(Settings())

    assert tools["search_code"].metadata["parallel_safe"] is True
    assert tools["search_code"].metadata["cacheable"] is True
    assert tools["search_code"].metadata["cache_scope"] == "thread"
    assert tools["web_search"].metadata["fallback_group"] == "web_search"
    assert tools["write_text_artifact"].metadata["side_effect"] is True


def test_web_search_falls_back_to_duckduckgo_when_tavily_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = [
        {"title": "DDG result", "href": "https://example.com/ddg", "body": "fallback content"},
    ]
    _FakeDDGS.raised = None
    tools = _tool_map(Settings())

    status, content = _runtime_invoke(tools["web_search"], {"query": "hello", "max_results": 4})
    payload = json.loads(content)

    assert status == "success"
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

    status, content = _runtime_invoke(tools["web_search"], {"query": "hello"})
    payload = json.loads(content)

    assert status == "success"
    assert payload["provider"] == "duckduckgo"
    assert payload["results"][0]["title"] == "Fallback"


def test_web_search_raises_when_both_providers_fail(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = []
    _FakeDDGS.raised = RuntimeError("ddg down")
    tools = _tool_map(Settings())

    status, content = _runtime_invoke(tools["web_search"], {"query": "hello"})

    assert status == "error"
    assert "ddg down" in content


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
    assert result == "artifact_saved:.focus_agent/artifacts/ai-notes.md"
    assert expected_path.read_text(encoding="utf-8") == "# AI Notes\n\nLocal only\n"


def test_write_text_artifact_keeps_readable_unicode_title_slug(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            artifact_dir=str(project / ".focus_agent" / "artifacts"),
        )
    )

    result = str(
        tools["write_text_artifact"].invoke(
            {
                "title": "小猫：人类最温柔的陪伴者",
                "body": "正文",
            }
        )
    )

    expected_path = project / ".focus_agent" / "artifacts" / "小猫人类最温柔的陪伴者.md"
    assert result == "artifact_saved:.focus_agent/artifacts/小猫人类最温柔的陪伴者.md"
    assert expected_path.read_text(encoding="utf-8") == "# 小猫：人类最温柔的陪伴者\n\n正文\n"


def test_artifact_tools_list_read_and_update_saved_artifacts(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    artifact_dir = project / ".focus_agent" / "artifacts"
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            artifact_dir=str(artifact_dir),
        )
    )

    tools["write_text_artifact"].invoke({"title": "Launch Plan", "body": "First draft"})
    list_payload = json.loads(tools["artifact_list"].invoke({}))
    read_payload = json.loads(tools["artifact_read"].invoke({"artifact_id": "launch-plan.md"}))
    update_payload = json.loads(
        tools["artifact_update"].invoke(
            {
                "artifact_id": "launch-plan.md",
                "body": "Second section",
                "mode": "append",
            }
        )
    )
    updated_read_payload = json.loads(tools["artifact_read"].invoke({"artifact_id": "launch-plan.md"}))

    assert list_payload["artifacts"][0]["artifact_id"] == "launch-plan.md"
    assert "First draft" in read_payload["content"]
    assert update_payload["mode"] == "append"
    assert "Second section" in updated_read_payload["content"]

    with pytest.raises(ValueError, match="artifact directory"):
        tools["artifact_read"].invoke({"artifact_id": "../outside.md"})


def test_artifact_tools_use_injected_metadata_repository_for_thread_scoped_listing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    artifact_dir = project / ".focus_agent" / "artifacts"
    artifact_dir.mkdir(parents=True)
    metadata_repo = _FakeArtifactMetadataRepository()
    monkeypatch.setattr("focus_agent.capabilities.default_tools._get_current_thread_id", lambda: "thread-1")
    tools = _tool_map(
        Settings(
            database_uri="postgresql://example.test/focus_agent",
            workspace_root=str(project),
            artifact_dir=str(artifact_dir),
        ),
        artifact_metadata_repository=metadata_repo,
    )

    tools["write_text_artifact"].invoke({"title": "Launch Plan", "body": "First draft"})
    (artifact_dir / "orphan.md").write_text("orphan\n", encoding="utf-8")
    (artifact_dir / "other-thread.md").write_text("other thread\n", encoding="utf-8")
    metadata_repo.upsert_from_file(
        thread_id="thread-2",
        artifact_id="other-thread.md",
        path=artifact_dir / "other-thread.md",
        title="Other Thread",
    )

    list_payload = json.loads(tools["artifact_list"].invoke({}))
    read_payload = json.loads(tools["artifact_read"].invoke({"artifact_id": "launch-plan.md"}))
    update_payload = json.loads(
        tools["artifact_update"].invoke(
            {
                "artifact_id": "launch-plan.md",
                "body": "Second section",
                "mode": "append",
            }
        )
    )

    assert [item["artifact_id"] for item in list_payload["artifacts"]] == ["launch-plan.md"]
    assert "First draft" in read_payload["content"]
    assert update_payload["artifact_id"] == "launch-plan.md"
    assert metadata_repo.upsert_calls[0]["thread_id"] == "thread-1"
    assert metadata_repo.upsert_calls[-1]["artifact_id"] == "launch-plan.md"


def test_web_fetch_extracts_html_text_and_blocks_localhost(monkeypatch):
    def fake_urlopen(request, timeout=0):
        assert request.full_url == "https://example.com/article"
        assert timeout == 30
        return _FakeHttpResponse(
            "<html><head><title>Example Title</title><script>ignore()</script></head>"
            "<body><h1>Hello</h1><p>Useful article text.</p></body></html>",
            url="https://example.com/article",
            content_type="text/html; charset=utf-8",
        )

    monkeypatch.setattr("focus_agent.capabilities.default_tools.urllib_request.urlopen", fake_urlopen)

    tools = _tool_map(Settings())
    payload = json.loads(tools["web_fetch"].invoke({"url": "https://example.com/article", "max_chars": 200}))

    assert payload["title"] == "Example Title"
    assert "Useful article text." in payload["content"]
    assert "ignore" not in payload["content"]

    with pytest.raises(ValueError, match="localhost"):
        tools["web_fetch"].invoke({"url": "http://localhost:8000/healthz"})


def test_memory_tools_save_search_and_forget(tmp_path):
    store = PersistentInMemoryStore(tmp_path / "store.pkl")
    tools = {
        tool.name: tool
        for tool in get_default_tools(
            Settings(),
            store=store,
        )
    }

    saved = json.loads(
        tools["memory_save"].invoke(
            {
                "content": "User prefers concise answers.",
                "kind": "user_preference",
                "scope": "user",
                "user_id": "researcher-1",
                "tags": ["style"],
            }
        )
    )
    searched = json.loads(
        tools["memory_search"].invoke(
            {
                "query": "concise",
                "user_id": "researcher-1",
            }
        )
    )
    forgotten = json.loads(
        tools["memory_forget"].invoke(
            {
                "memory_id": saved["memory_id"],
                "user_id": "researcher-1",
            }
        )
    )
    searched_again = json.loads(
        tools["memory_search"].invoke(
            {
                "query": "concise",
                "user_id": "researcher-1",
            }
        )
    )

    assert saved["saved"] is True
    assert saved["visibility"] == "shared"
    assert searched["results"][0]["content"] == "User prefers concise answers."
    assert searched["results"][0]["visibility"] == "shared"
    assert forgotten["deleted"] is True
    assert searched_again["results"] == []


def test_memory_save_accepts_conversation_scope_alias(tmp_path):
    store = PersistentInMemoryStore(tmp_path / "store.pkl")
    tools = {
        tool.name: tool
        for tool in get_default_tools(
            Settings(),
            store=store,
        )
    }

    saved = json.loads(
        tools["memory_save"].invoke(
            {
                "content": "This thread has an approved product-tools conclusion.",
                "kind": "imported_conclusion",
                "scope": "conversation",
                "root_thread_id": "thread-1",
            }
        )
    )
    searched = json.loads(
        tools["memory_search"].invoke(
            {
                "query": "product tools",
                "root_thread_id": "thread-1",
            }
        )
    )

    assert saved["scope"] == "root_thread"
    assert saved["visibility"] == "shared"
    assert saved["namespace"] == ["conversation", "thread-1", "main"]
    assert searched["results"][0]["memory_id"] == saved["memory_id"]
    assert searched["results"][0]["visibility"] == "shared"


def test_memory_save_reuses_writer_dedupe_for_same_user_preference_topic():
    store = _MemoryToolStore()
    tools = {
        tool.name: tool
        for tool in get_default_tools(
            Settings(),
            store=store,
        )
    }

    first = json.loads(
        tools["memory_save"].invoke(
            {
                "content": "请用中文回答。",
                "kind": "user_preference",
                "scope": "user",
                "user_id": "user-1",
            }
        )
    )
    second = json.loads(
        tools["memory_save"].invoke(
            {
                "content": "请用英文回答。",
                "kind": "user_preference",
                "scope": "user",
                "user_id": "user-1",
            }
        )
    )
    searched = json.loads(
        tools["memory_search"].invoke(
            {
                "query": "请用什么语言回答",
                "user_id": "user-1",
            }
        )
    )

    assert first["saved"] is True
    assert second["saved"] is True
    assert second["action"] == "merged"
    assert second["memory_id"] == first["memory_id"]
    assert len(store.data[("user", "user-1", "profile")]) == 1
    assert searched["results"][0]["content"] == "请用英文回答。"


def test_memory_search_reuses_retriever_dedupe_and_rerank_logic():
    profile_namespace = ("user", "user-1", "profile")
    store = _MemoryToolStore(
        {
            profile_namespace: [
                types.SimpleNamespace(
                    key="pref-old",
                    namespace=profile_namespace,
                    score=0.69,
                    value={
                        "kind": "user_preference",
                        "scope": "user",
                        "visibility": "shared",
                        "content": "请用中文回答。",
                        "summary": "请用中文回答。",
                        "user_id": "user-1",
                        "updated_at": "2026-04-22T08:00:00+00:00",
                    },
                ),
                types.SimpleNamespace(
                    key="pref-new",
                    namespace=profile_namespace,
                    score=0.67,
                    value={
                        "kind": "user_preference",
                        "scope": "user",
                        "visibility": "shared",
                        "content": "请用英文回答。",
                        "summary": "请用英文回答。",
                        "user_id": "user-1",
                        "updated_at": "2026-04-22T09:00:00+00:00",
                    },
                ),
            ]
        }
    )
    tools = {
        tool.name: tool
        for tool in get_default_tools(
            Settings(),
            store=store,
        )
    }

    searched = json.loads(
        tools["memory_search"].invoke(
            {
                "query": "请用什么语言回答",
                "user_id": "user-1",
            }
        )
    )

    assert len(searched["results"]) == 1
    assert searched["results"][0]["memory_id"] == "pref-new"
    assert searched["results"][0]["content"] == "请用英文回答。"


def test_conversation_summary_reads_latest_checkpoint(tmp_path):
    checkpointer = PersistentInMemorySaver(tmp_path / "checkpoints.pkl")
    builder = StateGraph(dict)
    builder.add_node(
        "write_state",
        lambda _state: {
            "rolling_summary": "User asked for tool design.",
            "task_brief": "Design tools",
            "active_skill_ids": ["research"],
            "messages": [
                HumanMessage(content="Summarize this"),
                AIMessage(content="Here is the summary."),
            ],
        },
    )
    builder.add_edge(START, "write_state")
    builder.add_edge("write_state", END)
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke({"messages": []}, config={"configurable": {"thread_id": "thread-1"}})
    tools = {
        tool.name: tool
        for tool in get_default_tools(
            Settings(),
            checkpointer=checkpointer,
        )
    }

    payload = json.loads(tools["conversation_summary"].invoke({"thread_id": "thread-1"}))

    assert payload["thread_id"] == "thread-1"
    assert payload["rolling_summary"] == "User asked for tool design."
    assert payload["recent_messages"][-1]["content"] == "Here is the summary."


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


def test_search_code_skips_local_focus_agent_runtime_dir(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / ".focus_agent" / "postgres" / "run").mkdir(parents=True)
    (project / "src" / "state.py").write_text("selected_model: str\n", encoding="utf-8")
    (project / ".focus_agent" / "postgres" / "run" / "noise.py").write_text(
        "selected_model = 'runtime'\n",
        encoding="utf-8",
    )
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(tools["search_code"].invoke({"query": "selected_model", "literal": True}))

    assert [item["path"] for item in payload["results"]] == ["src/state.py"]


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
