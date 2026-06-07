import json
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from langchain.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from focus_agent.capabilities.default_tool_modules.workspace_command import (
    validate_command_paths,
    workspace_command_allowed,
)
from focus_agent.capabilities.default_tools import get_default_tools
from focus_agent.capabilities.tool_manifest import normalize_tool_metadata
from focus_agent.capabilities.tool_registry import ToolRuntimeMeta
from focus_agent.capabilities.tool_runtime import ToolExecutionInput, execute_tool_calls
from focus_agent.config import (
    ApplyPatchToolConfig,
    GitLogToolConfig,
    ListFilesToolConfig,
    ReadFileToolConfig,
    RunWorkspaceCommandToolConfig,
    SearchCodeToolConfig,
    Settings,
    ToolCatalogConfig,
    WebFetchToolConfig,
    WebSearchConfig,
)
from focus_agent.core.types import ContextBudget
from focus_agent.engine.local_persistence import PersistentInMemorySaver, PersistentInMemoryStore
from focus_agent.memory import MemoryAuditEvent, MemoryRecord, MemorySearchHit, MemoryStatus
from focus_agent.repositories.productivity_repository import InMemoryProductivityRepository


class _FakeWebHttpClient:
    def __init__(self, *, post=None, get=None):
        self._post = post
        self._get = get

    def post(self, url, *, json=None, headers=None, timeout=None):
        if self._post is None:
            raise AssertionError(f"unexpected POST {url}")
        return self._post(url, json=json, headers=headers or {}, timeout=timeout)

    def get(self, url, *, headers=None, timeout=None):
        if self._get is None:
            raise AssertionError(f"unexpected GET {url}")
        return self._get(url, headers=headers or {}, timeout=timeout)


def _http_json_response(
    method: str, url: str, payload: object, *, status_code: int = 200
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request(method, url),
    )


def _http_text_response(
    method: str,
    url: str,
    body: str,
    *,
    content_type: str = "text/plain; charset=utf-8",
    headers: dict[str, str] | None = None,
    status_code: int = 200,
) -> httpx.Response:
    response_headers = {"content-type": content_type}
    response_headers.update(headers or {})
    return httpx.Response(
        status_code,
        text=body,
        headers=response_headers,
        request=httpx.Request(method, url),
    )


class _FakeDDGS:
    results = []
    raised = None
    last_query = None
    last_max_results = None
    call_count = 0

    def __init__(self, timeout=30):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def text(self, query, region="wt-wt", safesearch="moderate", max_results=5):
        _FakeDDGS.last_query = query
        _FakeDDGS.last_max_results = max_results
        _FakeDDGS.call_count += 1
        if _FakeDDGS.raised is not None:
            raise _FakeDDGS.raised
        return list(_FakeDDGS.results)


def _install_fake_ddgs(monkeypatch):
    fake_module = types.ModuleType("ddgs")
    fake_module.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake_module)


def _prepare_fake_ddgs(monkeypatch, *, results=None, raised=None):
    _install_fake_ddgs(monkeypatch)
    _FakeDDGS.results = list(results or [])
    _FakeDDGS.raised = raised
    _FakeDDGS.last_query = None
    _FakeDDGS.last_max_results = None
    _FakeDDGS.call_count = 0


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
            created_at=previous.created_at if previous is not None else datetime.now(UTC),
            updated_at=datetime.fromtimestamp(stat.st_mtime, UTC),
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
            record for record in self.records_by_id.values() if record.thread_id == thread_id
        ]
        records.sort(key=lambda record: (-record.updated_at.timestamp(), record.artifact_id))
        if limit is not None:
            return records[:limit]
        return records

    def get_by_artifact_id(self, artifact_id: str):
        return self.records_by_id.get(artifact_id)


class _MemoryToolStore:
    def __init__(
        self, search_results_by_namespace: dict[tuple[str, ...], list[object]] | None = None
    ):
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


class _MemoryToolRepository:
    def __init__(self):
        self.records: dict[str, MemoryRecord] = {}
        self.audit_events: list[MemoryAuditEvent] = []

    def find_existing(
        self,
        *,
        namespace: tuple[str, ...],
        fingerprint: str,
        semantic_key: str,
        kind: str | None = None,
        scope: str | None = None,
    ) -> MemoryRecord | None:
        for record in self.records.values():
            if record.namespace != namespace:
                continue
            if record.status == MemoryStatus.FORGOTTEN or record.deleted_at is not None:
                continue
            if kind and record.kind.value != kind:
                continue
            if scope and record.scope.value != scope:
                continue
            if record.fingerprint == fingerprint or record.semantic_key == semantic_key:
                return record
        return None

    def upsert_record(self, record: MemoryRecord) -> str:
        self.records[record.memory_id] = record
        return record.memory_id

    def search(
        self, *, namespace: tuple[str, ...], query: str, limit: int
    ) -> list[MemorySearchHit]:
        query_text = query.casefold()
        hits = [
            MemorySearchHit(record=record, score=0.6, namespace=record.namespace)
            for record in self.records.values()
            if record.namespace == namespace
            and record.status == MemoryStatus.ACTIVE
            and query_text in f"{record.summary} {record.content}".casefold()
        ]
        return hits[:limit]

    def forget_record(
        self,
        *,
        memory_id: str,
        namespace: tuple[str, ...] | None = None,
        actor: str | None = None,
        reason: str | None = None,
    ) -> str | None:
        del actor, reason
        record = self.records.get(memory_id)
        if record is None or (namespace is not None and record.namespace != namespace):
            return None
        self.records[memory_id] = record.model_copy(update={"status": MemoryStatus.FORGOTTEN})
        return f"tombstone-{memory_id}"

    def append_audit_event(self, event: MemoryAuditEvent) -> str:
        self.audit_events.append(event)
        return event.event_id

    def get_record(self, memory_id: str) -> MemoryRecord | None:
        return self.records.get(memory_id)

    def list_records(self, query):  # noqa: ANN001
        del query
        return list(self.records.values())


class _FakeMemoryEmbeddingService:
    def __init__(self) -> None:
        self.embedded_memory_ids: list[str] = []

    def ensure_embedding(self, record: MemoryRecord) -> dict[str, object]:
        self.embedded_memory_ids.append(record.memory_id)
        return {"memory_id": record.memory_id, "status": "written"}


def _tool_map(
    settings: Settings,
    *,
    artifact_metadata_repository=None,
    memory_repository=None,
    memory_embedding_service=None,
    productivity_repository=None,
) -> dict[str, object]:
    kwargs = {"artifact_metadata_repository": artifact_metadata_repository}
    if memory_repository is not None:
        kwargs["memory_repository"] = memory_repository
    if memory_embedding_service is not None:
        kwargs["memory_embedding_service"] = memory_embedding_service
    if productivity_repository is not None:
        kwargs["productivity_repository"] = productivity_repository
    return {tool.name: tool for tool in get_default_tools(settings, **kwargs)}


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


def _invoke_web_search_direct_and_runtime(tool_obj, args: dict[str, object]) -> dict[str, object]:
    direct_payload = json.loads(tool_obj.invoke(dict(args)))
    status, content = _runtime_invoke(tool_obj, dict(args))
    runtime_payload = json.loads(content)

    assert status == "success"
    assert runtime_payload == direct_payload
    return direct_payload


def _assert_web_search_stability_fields(
    payload: dict[str, object],
    *,
    provider: str,
    fallback_used: bool,
    attempted_providers: list[str],
) -> None:
    assert payload["provider"] == provider
    assert payload["fallback_used"] is fallback_used
    assert payload["attempted_providers"] == attempted_providers
    assert isinstance(payload["errors"], list)


def _assert_web_search_error_mentions(payload: dict[str, object], *fragments: str) -> None:
    errors = payload["errors"]
    assert isinstance(errors, list)
    haystacks = [json.dumps(error, sort_keys=True).lower() for error in errors]
    assert any(
        all(fragment.lower() in haystack for fragment in fragments) for haystack in haystacks
    )


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Focus Agent"], cwd=path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "focus-agent@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_web_search_prefers_tavily_when_available(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(monkeypatch)

    def fake_post(url, *, json=None, headers=None, timeout=0):
        del headers
        assert url == "https://api.tavily.com/search"
        assert timeout == 30
        assert json["query"] == "latest model release"
        assert json["max_results"] == 3
        return _http_json_response(
            "POST",
            url,
            {
                "answer": "A concise answer",
                "results": [
                    {"title": "Official docs", "url": "https://example.com/docs", "content": "doc"},
                    {
                        "title": "Release notes",
                        "url": "https://example.com/release",
                        "content": "notes",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=fake_post),
    )

    tools = _tool_map(Settings())
    payload = _invoke_web_search_direct_and_runtime(
        tools["web_search"],
        {"query": "latest model release", "max_results": 3},
    )

    assert payload["query"] == "latest model release"
    assert payload["answer"] == "A concise answer"
    assert payload["results"][0]["title"] == "Official docs"
    assert payload["results"][0]["url"] == "https://example.com/docs"
    assert payload["results"][0]["content"] == "doc"
    _assert_web_search_stability_fields(
        payload,
        provider="tavily",
        fallback_used=False,
        attempted_providers=["tavily"],
    )
    assert payload["errors"] == []
    assert _FakeDDGS.call_count == 0


def test_web_search_default_path_uses_shared_http_client(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(monkeypatch)

    def fake_post(url, *, json=None, headers=None, timeout=None):
        assert url == "https://api.tavily.com/search"
        assert headers["Authorization"] == "Bearer test-key"
        assert timeout == 30
        assert json == {
            "query": "shared transport",
            "max_results": 2,
            "include_answer": True,
        }
        return _http_json_response(
            "POST",
            url,
            {
                "answer": "Shared transport answer",
                "results": [
                    {
                        "title": "Shared",
                        "url": "https://example.com/shared",
                        "content": "transport",
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=fake_post),
    )

    tools = _tool_map(Settings())
    payload = json.loads(
        tools["web_search"].invoke({"query": "shared transport", "max_results": 2})
    )

    assert payload["provider"] == "tavily"
    assert payload["answer"] == "Shared transport answer"
    assert payload["results"][0]["url"] == "https://example.com/shared"


def test_web_search_uses_configured_api_key_env_from_settings(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)

    def fake_post(url, *, json=None, headers=None, timeout=0):
        del json, timeout
        assert headers["Authorization"] == "Bearer alt-key"
        return _http_json_response(
            "POST",
            url,
            {
                "answer": "Configured env",
                "results": [
                    {
                        "title": "Configured",
                        "url": "https://example.com/configured",
                        "content": "ok",
                    },
                ],
            },
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=fake_post),
    )

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
    assert tools["apply_patch"].metadata["requires_approval"] is True
    assert tools["apply_patch"].metadata["requires_workspace_write"] is True
    assert tools["apply_patch"].metadata["side_effect_kind"] == "workspace_write"
    assert tools["run_workspace_command"].metadata["side_effect"] is True
    assert tools["run_workspace_command"].metadata["requires_workspace_write"] is True
    assert tools["run_workspace_command"].metadata["requires_approval"] is True


def test_builtin_write_tools_keep_security_floor_when_metadata_overlay_downgrades():
    metadata = normalize_tool_metadata(
        name="apply_patch",
        overlay={
            "side_effect": False,
            "requires_workspace_write": False,
            "requires_approval": False,
            "risk_level": "low",
            "side_effect_kind": "read_only",
        },
    )

    assert metadata["side_effect"] is True
    assert metadata["requires_workspace_write"] is True
    assert metadata["requires_approval"] is True
    assert metadata["risk_level"] == "medium"
    assert metadata["side_effect_kind"] == "workspace_write"


def test_web_search_falls_back_to_duckduckgo_when_tavily_key_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _prepare_fake_ddgs(
        monkeypatch,
        results=[
            {"title": "DDG result", "href": "https://example.com/ddg", "body": "fallback content"},
        ],
    )
    tools = _tool_map(Settings())

    payload = _invoke_web_search_direct_and_runtime(
        tools["web_search"],
        {"query": "hello", "max_results": 4},
    )

    _assert_web_search_stability_fields(
        payload,
        provider="duckduckgo",
        fallback_used=True,
        attempted_providers=["tavily", "duckduckgo"],
    )
    assert payload["answer"] is None
    assert payload["results"][0]["url"] == "https://example.com/ddg"
    _assert_web_search_error_mentions(payload, "tavily", "key")
    assert _FakeDDGS.last_query == "hello"
    assert _FakeDDGS.last_max_results == 4
    assert _FakeDDGS.call_count == 2


@pytest.mark.parametrize(
    ("failure_kind", "expected_error_fragment"),
    [
        ("http_500", "500"),
        ("http_429", "429"),
        ("oserror", "temporary tavily outage"),
    ],
)
def test_web_search_retries_retryable_tavily_failures_then_falls_back(
    monkeypatch,
    failure_kind,
    expected_error_fragment,
):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(
        monkeypatch,
        results=[
            {"title": "Fallback", "link": "https://example.com/fallback", "snippet": "backup"},
        ],
    )
    tavily_attempts = 0

    def failing_post(url, *, json=None, headers=None, timeout=0):
        del json, headers, timeout
        nonlocal tavily_attempts
        tavily_attempts += 1
        if failure_kind == "http_500":
            return _http_json_response("POST", url, {"error": "tavily failed"}, status_code=500)
        if failure_kind == "http_429":
            return _http_json_response("POST", url, {"error": "tavily failed"}, status_code=429)
        raise httpx.ConnectError("temporary tavily outage", request=httpx.Request("POST", url))

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=failing_post),
    )
    tools = _tool_map(Settings())

    payload = _invoke_web_search_direct_and_runtime(tools["web_search"], {"query": "hello"})

    _assert_web_search_stability_fields(
        payload,
        provider="duckduckgo",
        fallback_used=True,
        attempted_providers=["tavily", "duckduckgo"],
    )
    assert payload["results"][0]["title"] == "Fallback"
    _assert_web_search_error_mentions(payload, "tavily", expected_error_fragment)
    assert tavily_attempts > 2
    assert _FakeDDGS.call_count == 2


def test_web_search_falls_back_to_duckduckgo_when_tavily_returns_empty_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(
        monkeypatch,
        results=[
            {"title": "Fallback", "href": "https://example.com/empty-fallback", "body": "backup"},
        ],
    )

    def empty_post(url, *, json=None, headers=None, timeout=0):
        del json, headers, timeout
        return _http_json_response("POST", url, {"answer": "No useful hits", "results": []})

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=empty_post),
    )
    tools = _tool_map(Settings())

    payload = _invoke_web_search_direct_and_runtime(tools["web_search"], {"query": "hello"})

    _assert_web_search_stability_fields(
        payload,
        provider="duckduckgo",
        fallback_used=True,
        attempted_providers=["tavily", "duckduckgo"],
    )
    assert payload["answer"] is None
    assert payload["results"][0]["url"] == "https://example.com/empty-fallback"
    _assert_web_search_error_mentions(payload, "tavily", "result")
    assert _FakeDDGS.call_count == 2


@pytest.mark.parametrize("status_code", [401, 403])
def test_web_search_does_not_retry_tavily_auth_failures_before_fallback(monkeypatch, status_code):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(
        monkeypatch,
        results=[
            {
                "title": "Auth fallback",
                "href": "https://example.com/auth-fallback",
                "body": "backup",
            },
        ],
    )
    tavily_attempts = 0

    def auth_post(url, *, json=None, headers=None, timeout=0):
        del json, headers, timeout
        nonlocal tavily_attempts
        tavily_attempts += 1
        return _http_json_response("POST", url, {"error": "tavily failed"}, status_code=status_code)

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=auth_post),
    )
    tools = _tool_map(Settings())

    payload = _invoke_web_search_direct_and_runtime(tools["web_search"], {"query": "hello"})

    _assert_web_search_stability_fields(
        payload,
        provider="duckduckgo",
        fallback_used=True,
        attempted_providers=["tavily", "duckduckgo"],
    )
    assert payload["results"][0]["title"] == "Auth fallback"
    _assert_web_search_error_mentions(payload, "tavily", str(status_code))
    assert tavily_attempts == 2
    assert _FakeDDGS.call_count == 2


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
    assert "apply_patch" in tools
    assert "run_workspace_command" in tools
    assert "git_status" in tools
    assert "git_diff" in tools
    assert "git_log" in tools


def test_disabled_tools_are_removed_from_registry(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_ddgs(monkeypatch)
    tools = _tool_map(
        Settings(
            tool_catalog=ToolCatalogConfig(
                apply_patch=ApplyPatchToolConfig(enabled=False),
                list_files=ListFilesToolConfig(enabled=False),
                run_workspace_command=RunWorkspaceCommandToolConfig(enabled=False),
                git_log=GitLogToolConfig(enabled=False),
            ),
            web_search=WebSearchConfig(provider="duckduckgo"),
        )
    )

    assert "list_files" not in tools
    assert "apply_patch" not in tools
    assert "run_workspace_command" not in tools
    assert "git_log" not in tools
    assert "read_file" in tools
    assert "web_search" in tools


def test_web_search_respects_duckduckgo_only_configuration(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    _prepare_fake_ddgs(
        monkeypatch,
        results=[
            {
                "title": "DDG only",
                "href": "https://example.com/ddg-only",
                "body": "fallback content",
            },
        ],
    )

    def unexpected_post(url, *, json=None, headers=None, timeout=0):
        del url, json, headers, timeout
        raise AssertionError("Tavily should not be called when provider=duckduckgo")

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(post=unexpected_post),
    )

    tools = _tool_map(
        Settings(web_search=WebSearchConfig(provider="duckduckgo", fallback_provider="tavily"))
    )
    payload = _invoke_web_search_direct_and_runtime(tools["web_search"], {"query": "hello"})

    _assert_web_search_stability_fields(
        payload,
        provider="duckduckgo",
        fallback_used=False,
        attempted_providers=["duckduckgo"],
    )
    assert payload["errors"] == []
    assert payload["results"][0]["title"] == "DDG only"
    assert _FakeDDGS.call_count == 2


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
    updated_read_payload = json.loads(
        tools["artifact_read"].invoke({"artifact_id": "launch-plan.md"})
    )

    assert list_payload["artifacts"][0]["artifact_id"] == "launch-plan.md"
    assert "First draft" in read_payload["content"]
    assert update_payload["mode"] == "append"
    assert "Second section" in updated_read_payload["content"]

    with pytest.raises(ValueError, match="artifact directory"):
        tools["artifact_read"].invoke({"artifact_id": "../outside.md"})


def test_artifact_tools_use_injected_metadata_repository_for_thread_scoped_listing(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    artifact_dir = project / ".focus_agent" / "artifacts"
    artifact_dir.mkdir(parents=True)
    metadata_repo = _FakeArtifactMetadataRepository()
    monkeypatch.setattr(
        "focus_agent.capabilities.default_tools._get_current_thread_id", lambda: "thread-1"
    )
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
    def fake_get(url, *, headers=None, timeout=0):
        del headers
        assert url == "https://example.com/article"
        assert timeout == 30
        return _http_text_response(
            "GET",
            url,
            "<html><head><title>Example Title</title><script>ignore()</script></head>"
            "<body><h1>Hello</h1><p>Useful article text.</p></body></html>",
            content_type="text/html; charset=utf-8",
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(get=fake_get),
    )

    tools = _tool_map(Settings())
    payload = json.loads(
        tools["web_fetch"].invoke({"url": "https://example.com/article", "max_chars": 200})
    )

    assert payload["title"] == "Example Title"
    assert "Useful article text." in payload["content"]
    assert "ignore" not in payload["content"]

    with pytest.raises(ValueError, match="localhost"):
        tools["web_fetch"].invoke({"url": "http://localhost:8000/healthz"})


def test_web_fetch_respects_configured_domain_policy(monkeypatch):
    def unexpected_get(url, *, headers=None, timeout=0):
        del url, headers, timeout
        raise AssertionError("Blocked web_fetch should not issue a network request.")

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(get=unexpected_get),
    )
    tools = _tool_map(
        Settings(
            tool_catalog=ToolCatalogConfig(
                web_fetch=WebFetchToolConfig(
                    blocked_domains=("blocked.example",),
                    allowed_domains=("docs.example",),
                )
            )
        )
    )

    with pytest.raises(ValueError, match="blocked_domain"):
        tools["web_fetch"].invoke({"url": "https://news.blocked.example/article"})
    with pytest.raises(ValueError, match="not_in_allowlist"):
        tools["web_fetch"].invoke({"url": "https://outside.example/article"})


def test_web_fetch_domain_policy_allows_matching_allowlist(monkeypatch):
    def fake_get(url, *, headers=None, timeout=0):
        del headers, timeout
        assert url == "https://guide.docs.example/article"
        return _http_text_response("GET", url, "Allowed article")

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(get=fake_get),
    )
    tools = _tool_map(
        Settings(
            tool_catalog=ToolCatalogConfig(
                web_fetch=WebFetchToolConfig(allowed_domains=("docs.example",))
            )
        )
    )

    payload = json.loads(tools["web_fetch"].invoke({"url": "https://guide.docs.example/article"}))

    assert payload["final_url"] == "https://guide.docs.example/article"
    assert payload["content"] == "Allowed article"


def test_web_fetch_follows_redirects_and_rechecks_policy(monkeypatch):
    seen_urls: list[str] = []

    def fake_get(url, *, headers=None, timeout=0):
        del headers, timeout
        seen_urls.append(url)
        if url == "https://iana.org/":
            return _http_text_response(
                "GET",
                url,
                "",
                headers={"location": "https://www.iana.org/"},
                status_code=301,
            )
        assert url == "https://www.iana.org/"
        return _http_text_response(
            "GET",
            url,
            "<html><head><title>IANA</title></head><body>Root zone coordination.</body></html>",
            content_type="text/html; charset=utf-8",
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(get=fake_get),
    )

    payload = json.loads(_tool_map(Settings())["web_fetch"].invoke({"url": "https://iana.org/"}))

    assert seen_urls == ["https://iana.org/", "https://www.iana.org/"]
    assert payload["final_url"] == "https://www.iana.org/"
    assert payload["title"] == "IANA"
    assert "Root zone coordination." in payload["content"]


def test_web_fetch_blocks_redirects_to_disallowed_hosts(monkeypatch):
    seen_urls: list[str] = []

    def fake_get(url, *, headers=None, timeout=0):
        del headers, timeout
        seen_urls.append(url)
        return _http_text_response(
            "GET",
            url,
            "",
            headers={"location": "http://127.0.0.1:8000/private"},
            status_code=302,
        )

    monkeypatch.setattr(
        "focus_agent.capabilities.default_tool_modules.web.shared_sync_http_client",
        lambda: _FakeWebHttpClient(get=fake_get),
    )

    with pytest.raises(ValueError, match="redirect blocked.*blocked_host"):
        _tool_map(Settings())["web_fetch"].invoke({"url": "https://example.com/start"})

    assert seen_urls == ["https://example.com/start"]


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


def test_memory_tools_use_repository_when_provided():
    repo = _MemoryToolRepository()
    embedding_service = _FakeMemoryEmbeddingService()
    tools = _tool_map(
        Settings(),
        memory_repository=repo,
        memory_embedding_service=embedding_service,
    )

    saved = json.loads(
        tools["memory_save"].invoke(
            {
                "content": "Repository-backed memory prefers concise answers.",
                "kind": "user_preference",
                "scope": "user",
                "user_id": "researcher-1",
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
    assert saved["action"] == "written"
    assert searched["results"][0]["memory_id"] == saved["memory_id"]
    assert searched["results"][0]["content"] == "Repository-backed memory prefers concise answers."
    assert forgotten["deleted"] is True
    assert searched_again["results"] == []
    assert embedding_service.embedded_memory_ids == [saved["memory_id"]]
    assert [event.actor for event in repo.audit_events] == [
        "memory_save_tool",
        "memory_forget_tool",
    ]


def test_productivity_tools_use_current_user_context():
    repo = InMemoryProductivityRepository()
    tools = _tool_map(Settings(), productivity_repository=repo)
    config = {"configurable": {"thread_id": "thread-1", "user_id": "researcher-1"}}

    note = json.loads(
        tools["notes_create"].invoke(
            {
                "title": "Capture idea",
                "body": "Make notes first-class.",
                "source_kind": "chat_answer",
                "source_id": "turn-1",
                "source_url": "/app/chat/thread-1",
                "pinned_context": {"thread_id": "thread-1"},
                "captured_from": "chat",
            },
            config=config,
        )
    )["note"]
    task = json.loads(
        tools["tasks_create"].invoke(
            {
                "title": "Follow up",
                "description": "Turn note into task.",
                "source_note_id": note["note_id"],
                "source_kind": "agent_team_review",
                "source_id": "review-1",
                "source_url": "/app/agent-team/session-1",
                "captured_from": "agent_team",
            },
            config=config,
        )
    )["task"]
    captured = json.loads(
        tools["productivity_capture"].invoke(
            {
                "capture_type": "task",
                "source_kind": "chat_answer",
                "title": "Ship capture tool",
                "content": "Expose explicit productivity capture.",
                "payload_json": '{"id":"turn-2","thread_id":"thread-1"}',
                "captured_from": "chat",
            },
            config=config,
        )
    )["task"]
    notes = json.loads(tools["notes_search"].invoke({"query": "first-class"}, config=config))
    tasks = json.loads(tools["tasks_list"].invoke({}, config=config))
    updated = json.loads(
        tools["tasks_update"].invoke(
            {"task_id": task["task_id"], "status": "completed"},
            config=config,
        )
    )["task"]

    assert note["user_id"] == "researcher-1"
    assert note["source_thread_id"] == "thread-1"
    assert note["source_kind"] == "chat_answer"
    assert note["source_id"] == "turn-1"
    assert note["source_url"] == "/app/chat/thread-1"
    assert note["pinned_context"] == {"thread_id": "thread-1"}
    assert note["captured_from"] == "chat"
    assert task["source_note_id"] == note["note_id"]
    assert task["source_kind"] == "agent_team_review"
    assert task["source_id"] == "review-1"
    assert task["captured_from"] == "agent_team"
    assert captured["title"] == "Ship capture tool"
    assert captured["source_kind"] == "chat_answer"
    assert captured["source_id"] == "turn-2"
    assert captured["source_thread_id"] == "thread-1"
    assert notes["count"] == 1
    assert tasks["count"] == 2
    assert updated["status"] == "completed"


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
        tools["read_file"].invoke({"path": "src/app.py", "start_line": 1, "end_line": 5})
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
    (project / ".claude" / "worktrees" / "stale-copy").mkdir(parents=True)
    (project / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (project / "node_modules" / "leftpad.js").write_text("module.exports = 1;\n", encoding="utf-8")
    (project / ".claude" / "worktrees" / "stale-copy" / "main.py").write_text(
        "print('stale')\n",
        encoding="utf-8",
    )
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
    (project / ".claude" / "worktrees" / "stale-copy" / "src").mkdir(parents=True)
    (project / "src" / "state.py").write_text("selected_model: str\n", encoding="utf-8")
    (project / ".focus_agent" / "postgres" / "run" / "noise.py").write_text(
        "selected_model = 'runtime'\n",
        encoding="utf-8",
    )
    (project / ".claude" / "worktrees" / "stale-copy" / "src" / "state.py").write_text(
        "selected_model = 'stale-worktree'\n",
        encoding="utf-8",
    )
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(tools["search_code"].invoke({"query": "selected_model", "literal": True}))

    assert [item["path"] for item in payload["results"]] == ["src/state.py"]


def test_search_code_includes_context_for_block_start_matches(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "settings.py"
    sample.write_text(
        "\n".join(
            [
                "TOOL_MANIFEST = {",
                '    "skill_install": {',
                '        "allowed_roles": ("skill_scout",),',
                '        "requires_workspace_write": True,',
                "    },",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(
        tools["search_code"].invoke(
            {"query": "skill_install", "path": "settings.py", "literal": True}
        )
    )

    result = payload["results"][0]
    assert result["line_number"] == 2
    assert '"allowed_roles": ("skill_scout",),' in result["context"]
    assert '"requires_workspace_write": True,' in result["context"]


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


def test_apply_patch_modifies_text_files_and_stays_within_workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sample = project / "src" / "app.py"
    sample.parent.mkdir()
    sample.write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    patch = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def greet():
-    return 'hi'
+    return 'hello'
"""
    payload = json.loads(tools["apply_patch"].invoke({"patch": patch}))

    assert payload["applied"] is True
    assert payload["changed_files"] == ["src/app.py"]
    assert sample.read_text(encoding="utf-8") == "def greet():\n    return 'hello'\n"

    outside_patch = """diff --git a/../outside.txt b/../outside.txt
--- a/../outside.txt
+++ b/../outside.txt
@@ -1 +1 @@
-outside
+changed
"""
    with pytest.raises(ValueError, match="workspace root"):
        tools["apply_patch"].invoke({"patch": outside_patch})

    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 'outside'\n", encoding="utf-8")
    link = project / "linked.py"
    try:
        link.symlink_to(outside)
    except OSError:
        return
    symlink_patch = """diff --git a/linked.py b/linked.py
--- a/linked.py
+++ b/linked.py
@@ -1 +1 @@
-VALUE = 'outside'
+VALUE = 'changed'
"""
    with pytest.raises(ValueError, match="workspace root"):
        tools["apply_patch"].invoke({"patch": symlink_patch})
    assert outside.read_text(encoding="utf-8") == "VALUE = 'outside'\n"


def test_apply_patch_rejects_binary_files_and_large_patches(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    binary = project / "data.bin"
    binary.write_bytes(b"\x00\x01demo\n")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                apply_patch=ApplyPatchToolConfig(max_patch_bytes=32),
            ),
        )
    )

    too_large_patch = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1 +1 @@
-a
+b
"""
    with pytest.raises(ValueError, match="max_patch_bytes"):
        tools["apply_patch"].invoke({"patch": too_large_patch})

    tools = _tool_map(Settings(workspace_root=str(project)))
    binary_patch = """diff --git a/data.bin b/data.bin
--- a/data.bin
+++ b/data.bin
@@ -1 +1 @@
-demo
+changed
"""
    with pytest.raises(ValueError, match="binary file"):
        tools["apply_patch"].invoke({"patch": binary_patch})


def test_apply_patch_rejects_symlink_and_submodule_patches(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    tools = _tool_map(Settings(workspace_root=str(project)))

    symlink_patch = """diff --git a/link b/link
new file mode 120000
index 0000000..dce0f2b
--- /dev/null
+++ b/link
@@ -0,0 +1 @@
+/tmp/outside
\\ No newline at end of file
"""
    submodule_patch = """diff --git a/vendor/lib b/vendor/lib
new file mode 160000
index 0000000..1111111
--- /dev/null
+++ b/vendor/lib
@@ -0,0 +1 @@
+Subproject commit 1111111111111111111111111111111111111111
"""

    with pytest.raises(ValueError, match="Symlink and submodule"):
        tools["apply_patch"].invoke({"patch": symlink_patch})
    with pytest.raises(ValueError, match="Symlink and submodule"):
        tools["apply_patch"].invoke({"patch": submodule_patch})

    assert not (project / "link").is_symlink()
    assert not (project / "vendor").exists()


def test_run_workspace_command_runs_allowlisted_commands_and_blocks_unsafe_ones(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    pytest_script = project / "pytest"
    pytest_script.write_text(
        "#!/bin/sh\necho 'pytest 9.0.0'\necho \"secret=${OPENAI_API_KEY:-missing}\"\n",
        encoding="utf-8",
    )
    pytest_script.chmod(0o755)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            tool_catalog=ToolCatalogConfig(
                run_workspace_command=RunWorkspaceCommandToolConfig(
                    default_timeout_seconds=5,
                    max_timeout_seconds=10,
                    max_output_chars=2000,
                )
            ),
        )
    )

    payload = json.loads(
        tools["run_workspace_command"].invoke(
            {"command": ["./pytest", "--version"], "timeout_seconds": 10}
        )
    )

    assert payload["command"] == ["./pytest", "--version"]
    assert payload["cwd"] == "."
    assert payload["exit_code"] == 0
    assert "pytest" in payload["stdout"].lower()
    assert "secret=missing" in payload["stdout"]
    assert "sk-test-secret" not in payload["stdout"]

    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke({"command": ["sh", "-c", "echo unsafe"]})
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke({"command": ["pnpm", "install"]})
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke({"command": ["ruff", "check", "--fix", "."]})
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke({"command": ["ruff", "format", "."]})
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke({"command": ["uv", "run", "ruff", "check", "--fix"]})
    with pytest.raises(ValueError, match="valid list"):
        tools["run_workspace_command"].invoke({"command": "pytest; touch pwned"})
    with pytest.raises(ValueError, match="workspace root"):
        tools["run_workspace_command"].invoke({"command": ["./pytest", "--version"], "cwd": ".."})
    with pytest.raises(ValueError, match="workspace root"):
        tools["run_workspace_command"].invoke({"command": [str(tmp_path / "pytest"), "--version"]})
    with pytest.raises(ValueError, match="workspace root"):
        tools["run_workspace_command"].invoke(
            {"command": ["./pytest", "--rootdir=/tmp", "--version"]}
        )
    assert not (project / "pwned").exists()


def test_run_workspace_command_allows_trusted_local_skill_python_scripts(tmp_path):
    project = tmp_path / "project"
    skill_dir = project / ".focus_agent" / "skills" / "stocks"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "stocks_client.py").write_text(
        "import json, sys\nprint(json.dumps({'argv': sys.argv[1:]}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    (skill_dir / "unsafe.py").write_text("print('nope')\n", encoding="utf-8")
    tools = _tool_map(Settings(workspace_root=str(project)))

    payload = json.loads(
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "scripts/stocks_client.py", "search", "南网能源"],
                "cwd": ".focus_agent/skills/stocks",
            }
        )
    )

    assert payload["exit_code"] == 0
    assert '"南网能源"' in payload["stdout"]
    virtual_args = {
        "command": ["python3", "scripts/stocks_client.py", "search", "南网能源"],
        "cwd": "/home/focus/.focus_agent/skills/stocks",
    }
    tools["run_workspace_command"].metadata["validator"](virtual_args)
    assert virtual_args["cwd"] == ".focus_agent/skills/stocks"

    virtual_payload = json.loads(tools["run_workspace_command"].invoke(virtual_args))
    assert virtual_payload["exit_code"] == 0
    assert virtual_payload["cwd"] == ".focus_agent/skills/stocks"
    assert '"南网能源"' in virtual_payload["stdout"]

    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "scripts/stocks_client.py", "search", "南网能源"],
                "cwd": ".",
            }
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "unsafe.py"],
                "cwd": ".focus_agent/skills/stocks",
            }
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": [
                    "python3",
                    "/home/focus/.focus_agent/skills/stocks/scripts/stocks_client.py",
                ],
                "cwd": "/home/focus/.focus_agent/skills/stocks",
            }
        )


def test_run_workspace_command_rejects_unconfigured_workspace_skills_root_scripts_by_default(
    tmp_path,
):
    project = tmp_path / "project"
    skill_dir = project / "skills" / "not-installed"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    marker = project / "pwned"
    (scripts_dir / "run.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    tools = _tool_map(Settings(workspace_root=str(project)))

    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "scripts/run.py"],
                "cwd": "skills/not-installed",
            }
        )

    assert not marker.exists()


def test_run_workspace_command_allows_trusted_workspace_skills_root_scripts(tmp_path):
    project = tmp_path / "project"
    skill_dir = project / "skills" / "stocks"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "stocks_client.py").write_text(
        "import json, sys\nprint(json.dumps({'argv': sys.argv[1:]}, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            skill_directories=("skills",),
            skill_install_directory="skills",
        )
    )

    payload = json.loads(
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "scripts/stocks_client.py", "search", "南网能源"],
                "cwd": "skills/stocks",
            }
        )
    )

    assert payload["exit_code"] == 0
    assert payload["cwd"] == "skills/stocks"
    assert '"南网能源"' in payload["stdout"]


def test_run_workspace_command_rejects_skill_script_interpreter_paths(tmp_path):
    project = tmp_path / "project"
    skill_dir = project / ".focus_agent" / "skills" / "stocks"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "stocks_client.py").write_text("print('real script')\n", encoding="utf-8")
    fake_python = skill_dir / "python3"
    fake_python.write_text("#!/bin/sh\necho fake interpreter\n", encoding="utf-8")
    fake_python.chmod(0o755)
    tools = _tool_map(Settings(workspace_root=str(project)))

    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": [".focus_agent/skills/stocks/python3", "scripts/stocks_client.py"],
                "cwd": ".focus_agent/skills/stocks",
            }
        )


def test_run_workspace_command_rejects_workspace_skill_root_escape(tmp_path):
    project = tmp_path / "project"
    skill_dir = project / "skills" / "stocks"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "stocks_client.py").write_text("print('ok')\n", encoding="utf-8")
    outside_skill = project / "outside-skill"
    outside_skill.mkdir()
    (skill_dir / "escape").symlink_to(outside_skill, target_is_directory=True)
    tools = _tool_map(
        Settings(
            workspace_root=str(project),
            skill_directories=("skills",),
            skill_install_directory="skills",
        )
    )

    with pytest.raises(ValueError, match="not allowlisted"):
        tools["run_workspace_command"].invoke(
            {
                "command": ["python3", "scripts/stocks_client.py"],
                "cwd": "skills/stocks/escape",
            }
        )


def test_run_workspace_command_rejects_unsafe_virtual_skill_cwd(tmp_path):
    project = tmp_path / "project"
    skill_dir = project / ".focus_agent" / "skills" / "stocks"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "stocks_client.py").write_text("print('ok')\n", encoding="utf-8")
    outside_skill = project / "outside-skill"
    outside_skill.mkdir()
    (skill_dir / "escape").symlink_to(outside_skill, target_is_directory=True)
    tools = _tool_map(Settings(workspace_root=str(project)))

    command = ["python3", "scripts/stocks_client.py"]
    for cwd, error in (
        ("/home/focus/.focus_agent/skills", "skill id"),
        ("/home/focus/.focus_agent/tools/stocks", "start"),
        ("/home/focus/.focus_agent/skills/stocks/../stocks", r"\.\."),
        ("/home/focus/.focus_agent/skills/stocks/escape", "escape"),
    ):
        with pytest.raises(ValueError, match=error):
            tools["run_workspace_command"].invoke({"command": command, "cwd": cwd})


def test_run_workspace_command_path_validation_ignores_scoped_package_filters(tmp_path):
    resolved_paths: list[str] = []

    def resolve_path(raw_path: str) -> Path:
        resolved_paths.append(raw_path)
        candidate = (tmp_path / raw_path).resolve()
        candidate.relative_to(tmp_path.resolve())
        return candidate

    for command in (
        ["pnpm", "--filter", "@focus-agent/web-app", "check"],
        ["pnpm", "--filter=@focus-agent/web-app", "check"],
    ):
        assert workspace_command_allowed(command, {"pnpm"})
        validate_command_paths(command, resolve_path=resolve_path)

    assert resolved_paths == []


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
