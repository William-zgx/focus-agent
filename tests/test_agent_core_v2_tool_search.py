from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain.tools import tool
from langchain_core.tools import StructuredTool

from focus_agent.capabilities.mcp_tools import _build_tool
from focus_agent.capabilities.tool_manifest import ToolManifest
from focus_agent.capabilities.tool_registry import ToolRegistry, ToolRuntimeMeta
from focus_agent.config import MCPServerConfig, Settings, load_tool_catalog_document
from focus_agent.config_parts.agent import load_agent_config
from focus_agent.core.request_context import RequestContext
from focus_agent.engine.loop.agent import make_loop_agent_node
from focus_agent.engine.loop.components import GraphComponents
from focus_agent.engine.loop.tool_search import (
    build_tool_search_tool,
    make_loop_tool_executor,
    tool_is_deferred,
    with_tool_search,
)
from focus_agent.harness.agents.definition import AgentDefinition, AgentDefinitionRegistry

from .test_agent_core_v2 import _ask, _invoke, _ScriptedModel, _v2_graph


class _OrderRecordingModel(_ScriptedModel):
    def __init__(self, responses):
        super().__init__(responses)
        self.raw_bound_tool_names: list[list[str]] = []

    def bind_tools(self, tools, **kwargs):
        self.raw_bound_tool_names.append([str(getattr(item, "name", "")) for item in tools])
        return super().bind_tools(tools, **kwargs)


def _components_with_tool_search(settings: Settings, tools: tuple) -> GraphComponents:
    registry = ToolRegistry(tools=tools)
    return with_tool_search(
        settings=settings,
        components=GraphComponents(
            skill_registry=None,
            tool_registry=registry,
            tools=list(registry.tools),
            memory_retriever=None,
            memory_writer=None,
            memory_extractor=None,
            model_factory=None,
        ),
    )


@tool
def deferred_lookup(name: str) -> str:
    """Look up a deferred project fact by name."""
    return f"deferred-fact:{name}"


deferred_lookup.metadata = {
    "defer_loading": True,
    "parallel_safe": True,
    "cacheable": False,
    "intent_tags": ("project_facts",),
    "toolset": "workspace",
}


def _call(call_id: str, name: str, args: dict) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"id": call_id, "name": name, "args": args}],
    )


def _policy_prompt(prompt: list) -> str:
    return next(
        message.content
        for message in prompt
        if isinstance(message, SystemMessage) and "## How to work" in message.content
    )


def _tool_messages(result) -> list[ToolMessage]:
    return [message for message in result.value["messages"] if isinstance(message, ToolMessage)]


def test_deferred_tool_loads_once_and_prompt_stays_stable(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _call("search-1", "tool_search", {"query": "select:deferred_lookup"}),
            AIMessage(content="Loaded for this turn."),
            AIMessage(content="Still loaded."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(deferred_lookup,))

    first = _invoke(graph, _ask("Load the deferred lookup"), "thread-deferred")
    second = _invoke(graph, _ask("Use it on the next turn"), "thread-deferred")

    assert "deferred_lookup" not in model.bound_tool_names[0]
    assert "tool_search" in model.bound_tool_names[0]
    assert "deferred_lookup" in model.bound_tool_names[1]
    assert "deferred_lookup" in model.bound_tool_names[2]
    search_result = _tool_messages(first)[0]
    assert search_result.status == "success"
    assert search_result.content.startswith("Loaded tools: deferred_lookup\n")
    assert second.value["messages"][-1].content == "Still loaded."
    prompts = [_policy_prompt(prompt) for prompt in model.prompts]
    assert "## Deferred tools" in prompts[0]
    assert "- deferred_lookup: Look up a deferred project fact by name." in prompts[0]
    assert prompts[0] == prompts[1] == prompts[2]


def test_failed_tool_search_does_not_load_a_deferred_tool(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _call("search-bad", "tool_search", {"query": ""}),
            AIMessage(content="The search failed."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(deferred_lookup,))

    result = _invoke(graph, _ask("Try an invalid search"), "thread-search-failed")

    assert _tool_messages(result)[0].status == "error"
    assert "deferred_lookup" not in model.bound_tool_names[0]
    assert "deferred_lookup" not in model.bound_tool_names[1]


def test_direct_deferred_call_executes_and_stays_bound(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _call("direct-1", "deferred_lookup", {"name": "focus"}),
            AIMessage(content="Direct call complete."),
            AIMessage(content="Next turn complete."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(deferred_lookup,))

    first = _invoke(graph, _ask("Call it directly"), "thread-direct-deferred")
    _invoke(graph, _ask("Continue"), "thread-direct-deferred")

    assert "deferred_lookup" not in model.bound_tool_names[0]
    assert _tool_messages(first)[0].content == "deferred-fact:focus"
    assert "deferred_lookup" in model.bound_tool_names[1]
    assert "deferred_lookup" in model.bound_tool_names[2]


def test_loaded_tool_survives_a_compacted_model_view():
    settings = Settings()
    components = _components_with_tool_search(settings, (deferred_lookup,))
    model = _ScriptedModel([AIMessage(content="Answer after compaction.")])
    node = make_loop_agent_node(
        settings=settings,
        tools=components.tools,
        model_for=lambda *_args: model,
        model_with_tools_for=lambda _model, _thinking, tools: model.bind_tools(tools),
    )
    latest = HumanMessage(content="What should I answer now?")
    state = {
        "messages": [
            HumanMessage(content="Load the lookup before compaction."),
            _call("old-search", "tool_search", {"query": "select:deferred_lookup"}),
            ToolMessage(
                content="Loaded tools: deferred_lookup\n- deferred_lookup: Lookup.",
                tool_call_id="old-search",
                status="success",
            ),
            AIMessage(content="Earlier answer."),
            latest,
        ],
        # The model sees only this compacted tail; loading uses the full transcript above.
        "recent_messages": [latest],
        "assembled_context": "",
        "llm_calls": 0,
    }
    runtime = SimpleNamespace(
        context=RequestContext(user_id="user-1", root_thread_id="thread-compacted-search")
    )

    node(state, runtime)

    assert "deferred_lookup" in model.bound_tool_names[0]
    assert [
        message.content for message in model.prompts[0] if isinstance(message, HumanMessage)
    ] == [latest.content]


def test_loaded_deferred_tools_follow_core_tools_in_registry_order():
    @tool
    def eager_lookup() -> str:
        """Look up an eager fact."""
        return "eager"

    @tool
    def later_deferred() -> str:
        """Look up another deferred fact."""
        return "later"

    later_deferred.metadata = {"defer_loading": True}
    settings = Settings()
    components = _components_with_tool_search(
        settings,
        (deferred_lookup, eager_lookup, later_deferred),
    )
    model = _OrderRecordingModel([AIMessage(content="done")])
    node = make_loop_agent_node(
        settings=settings,
        tools=components.tools,
        model_for=lambda *_args: model,
        model_with_tools_for=lambda _model, _thinking, tools: model.bind_tools(tools),
    )
    state = {
        "messages": [
            HumanMessage(content="Load both deferred tools."),
            _call(
                "ordered-search",
                "tool_search",
                {"query": "select:deferred_lookup,later_deferred"},
            ),
            ToolMessage(
                content="Loaded tools: deferred_lookup, later_deferred",
                tool_call_id="ordered-search",
                status="success",
            ),
        ],
        "assembled_context": "",
        "llm_calls": 0,
    }
    runtime = SimpleNamespace(
        context=RequestContext(user_id="user-1", root_thread_id="thread-ordered-search")
    )

    node(state, runtime)

    assert model.raw_bound_tool_names[0] == [
        "eager_lookup",
        "tool_search",
        "deferred_lookup",
        "later_deferred",
    ]


def test_agent_definition_excludes_deferred_tool_from_listing_and_search():
    definitions = AgentDefinitionRegistry(
        [
            AgentDefinition(
                name="restricted",
                description="Deny the deferred lookup.",
                tools_denied=["deferred_lookup"],
            )
        ]
    )
    settings = Settings()
    components = _components_with_tool_search(settings, (deferred_lookup,))
    model = _ScriptedModel([AIMessage(content="The tool is unavailable.")])
    node = make_loop_agent_node(
        settings=settings,
        tools=components.tools,
        model_for=lambda *_args: model,
        model_with_tools_for=lambda _model, _thinking, tools: model.bind_tools(tools),
        agent_definition_registry=definitions,
    )
    runtime = SimpleNamespace(
        context=RequestContext(user_id="user-1", root_thread_id="thread-restricted")
    )
    state = {
        "messages": [HumanMessage(content="Find the lookup")],
        "agent_name": "restricted",
        "assembled_context": "",
        "llm_calls": 0,
    }

    node(state, runtime)

    assert set(model.bound_tool_names[0]) == {"tool_search"}
    assert "## Deferred tools" not in "\n".join(
        message.content for message in model.prompts[0] if isinstance(message, SystemMessage)
    )

    executor = make_loop_tool_executor(
        settings=settings,
        components=components,
        approval_queue=None,
        harness_services=None,
        agent_definition_registry=definitions,
    )
    search_state = {
        **state,
        "messages": [
            *state["messages"],
            _call("search-restricted", "tool_search", {"query": "select:deferred_lookup"}),
        ],
    }
    updates = executor(search_state, runtime)
    search_result = updates["messages"][0]
    assert search_result.status == "success"
    assert "nothing was loaded" in search_result.content
    assert "Unknown or unavailable tools: deferred_lookup" in search_result.content

    direct_state = {
        **state,
        "messages": [
            *state["messages"],
            _call("direct-restricted", "deferred_lookup", {"name": "focus"}),
        ],
    }
    direct_result = executor(direct_state, runtime)["messages"][0]
    assert direct_result.status == "error"
    assert "deferred_lookup" in direct_result.content


def test_deferred_tools_kill_switch_restores_eager_binding(monkeypatch, tmp_path):
    model = _ScriptedModel([AIMessage(content="All tools are eager.")])
    graph = _v2_graph(
        monkeypatch,
        model,
        tmp_path,
        tools=(deferred_lookup,),
        agent_deferred_tools_enabled=False,
    )

    _invoke(graph, _ask("Use the old behavior"), "thread-deferral-off")

    assert model.bound_tool_names == [["deferred_lookup", "run_subtask", "todo_write"]]
    assert "## Deferred tools" not in _policy_prompt(model.prompts[0])


def test_deferred_tools_env_kill_switch():
    assert Settings().agent_deferred_tools_enabled is True
    assert (
        load_agent_config({"AGENT_DEFERRED_TOOLS_ENABLED": "false"}, Settings())[
            "agent_deferred_tools_enabled"
        ]
        is False
    )


def test_tool_search_select_unknown_and_keyword_paths():
    search = build_tool_search_tool([deferred_lookup])

    selected = search.invoke({"query": "select:deferred_lookup,missing_tool"})
    assert selected.startswith("Loaded tools: deferred_lookup\n")
    assert "Unknown or unavailable tools: missing_tool" in selected
    assert "can be called" in selected

    keyword = search.invoke({"query": "project_facts"})
    assert keyword.startswith("Loaded tools: deferred_lookup\n")
    exact_keyword = search.invoke({"query": "deferred_lookup"})
    assert exact_keyword.startswith("Loaded tools: deferred_lookup\n")

    no_match = search.invoke({"query": "unrelated capability"})
    assert "No deferred tools matched" in no_match
    assert "deferred_lookup" in no_match


def test_tool_search_name_hits_rank_above_description_hits():
    @tool
    def notes_lookup() -> str:
        """Look up notes by exact name."""
        return "notes"

    @tool
    def alpha() -> str:
        """Search notes through a description-only hit."""
        return "alpha"

    search = build_tool_search_tool([alpha, notes_lookup])

    result = search.invoke({"query": "notes"})

    assert result.splitlines()[1].startswith("- notes_lookup:")


def test_tool_search_clamps_keyword_result_limit():
    def noop() -> str:
        return "ok"

    deferred = [
        StructuredTool.from_function(
            func=noop,
            name=f"deferred_{index}",
            description="Common deferred capability.",
        )
        for index in range(12)
    ]
    search = build_tool_search_tool(deferred)

    one = search.invoke({"query": "common", "max_results": 0})
    ten = search.invoke({"query": "common", "max_results": 99})

    assert one.splitlines()[0] == "Loaded tools: deferred_0"
    assert len(ten.splitlines()[0].removeprefix("Loaded tools: ").split(", ")) == 10


def test_tool_search_runtime_metadata_is_read_only_and_unguarded():
    runtime = ToolRuntimeMeta.from_tool(build_tool_search_tool([deferred_lookup]))

    assert runtime.parallel_safe is True
    assert runtime.side_effect is False
    assert runtime.cacheable is False
    assert runtime.requires_approval is False
    assert runtime.risk_level == "low"


def test_toml_defer_loading_override_keeps_tool_core(monkeypatch, tmp_path):
    @tool
    def run_workspace_command() -> str:
        """Run an allowlisted workspace command."""
        return "ok"

    @tool
    def apply_patch() -> str:
        """Apply a patch to the workspace."""
        return "patched"

    catalog_path = tmp_path / "tools.toml"
    catalog_path.write_text("[run_workspace_command]\ndefer_loading = false\n", encoding="utf-8")
    catalog = load_tool_catalog_document(catalog_path)
    registry = ToolRegistry(
        tools=(run_workspace_command, apply_patch),
        manifests=(
            ToolManifest.from_tool(
                run_workspace_command,
                overlay=catalog.metadata_overlay_for("run_workspace_command"),
            ),
            ToolManifest.from_tool(
                apply_patch,
                overlay=catalog.metadata_overlay_for("apply_patch"),
            ),
        ),
    )
    model = _ScriptedModel([AIMessage(content="done")])
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=registry.tools)

    _invoke(graph, _ask("Inspect the repository"), "thread-toml-override")

    assert tool_is_deferred(run_workspace_command) is False
    assert tool_is_deferred(apply_patch) is True
    assert "run_workspace_command" in model.bound_tool_names[0]
    assert "apply_patch" not in model.bound_tool_names[0]
    assert "tool_search" in model.bound_tool_names[0]


@pytest.mark.parametrize("defer_loading", [True, False])
def test_mcp_server_defer_loading_controls_binding(monkeypatch, tmp_path, defer_loading):
    server = MCPServerConfig(
        name="demo",
        transport="stdio",
        command="python",
        defer_loading=defer_loading,
    )
    remote = SimpleNamespace(
        name="add",
        description="Add two integers.",
        annotations=SimpleNamespace(readOnlyHint=True),
        inputSchema={"type": "object", "properties": {}},
    )
    mcp_tool = _build_tool(server, remote, "mcp__demo__add")
    model = _ScriptedModel([AIMessage(content="done")])
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(mcp_tool,))

    _invoke(graph, _ask("Use MCP"), f"thread-mcp-{defer_loading}")

    assert tool_is_deferred(mcp_tool) is defer_loading
    assert ("mcp__demo__add" in model.bound_tool_names[0]) is not defer_loading
    assert ("tool_search" in model.bound_tool_names[0]) is defer_loading


def test_mcp_catalog_parses_defer_loading(tmp_path):
    catalog_path = tmp_path / "tools.toml"
    catalog_path.write_text(
        """
[[mcp_servers]]
name = "demo"
transport = "stdio"
command = "python"
defer_loading = false
""",
        encoding="utf-8",
    )

    catalog = load_tool_catalog_document(catalog_path)

    assert catalog.mcp_servers[0].defer_loading is False


def test_subtask_has_tool_search_with_an_independent_empty_loaded_set(monkeypatch, tmp_path):
    model = _ScriptedModel(
        [
            _call("parent-search", "tool_search", {"query": "select:deferred_lookup"}),
            _call(
                "delegate-1",
                "run_subtask",
                {"description": "Research", "prompt": "Research the deferred capability."},
            ),
            AIMessage(content="Subtask answer."),
            AIMessage(content="Parent answer."),
        ]
    )
    graph = _v2_graph(monkeypatch, model, tmp_path, tools=(deferred_lookup,))

    _invoke(graph, _ask("Delegate after loading"), "thread-subtask-search")

    assert "deferred_lookup" in model.bound_tool_names[1]
    child_names = model.bound_tool_names[2]
    assert "tool_search" in child_names
    assert "deferred_lookup" not in child_names
    assert "run_subtask" not in child_names
    assert any(
        isinstance(message, SystemMessage) and "fresh sub-agent" in message.content
        for message in model.prompts[2]
    )
