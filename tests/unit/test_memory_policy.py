from langchain.messages import AIMessage

from focus_agent.core.request_context import RequestContext
from focus_agent.memory import MemoryKind, MemoryScope, MemoryVisibility, MemoryWriter
from focus_agent.memory.models import MemoryWriteRequest
from focus_agent.storage.namespaces import project_memory_namespace
from tests.test_memory_pipeline import _SearchAllStore


def test_memory_writer_replaces_project_overlap_with_generated_semantic_keys():
    store = _SearchAllStore()
    writer = MemoryWriter(store=store)
    context = RequestContext(user_id="user-1", root_thread_id="thread-1", project_id="proj-1")
    state = {"messages": [AIMessage(content="项目部署分支已更新。")]}
    namespace = project_memory_namespace("proj-1")
    first = MemoryWriteRequest(
        kind=MemoryKind.PROJECT_FACT,
        scope=MemoryScope.PROJECT,
        visibility=MemoryVisibility.SHARED,
        namespace=namespace,
        content="Project deploys from the release branch.",
        summary="Project deploys from the release branch.",
        user_id="user-1",
        root_thread_id="thread-1",
        importance=0.75,
    )
    second = first.model_copy(
        update={
            "content": "Project deploys from the main branch.",
            "summary": "Project deploys from the main branch.",
        }
    )

    writer.persist_records([first], context=context, state=state)
    outcome = writer.persist_records([second], context=context, state=state)

    assert outcome["written"] == []
    assert len(outcome["merged"]) == 1
    assert len(store.data[namespace]) == 1
    payload = next(iter(store.data[namespace].values()))
    assert payload["content"] == second.content
    assert payload["summary"] == second.summary
