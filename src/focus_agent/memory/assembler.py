from __future__ import annotations

from .models import RetrievedMemoryBundle


def build_memory_blocks(bundle: RetrievedMemoryBundle) -> dict[str, list[str]]:
    lines = []
    for hit in bundle.hits:
        summary = hit.record.summary or hit.record.content
        score = f"{hit.score:.2f}"
        lines.append(f"{summary} [score {score}]")
    return {"retrieved_memories": lines}


def render_memory_block(bundle: RetrievedMemoryBundle) -> str:
    blocks = build_memory_blocks(bundle)
    lines = blocks["retrieved_memories"]
    if not lines:
        return "## Retrieved long-term memories\n(none)"
    return "## Retrieved long-term memories\n" + "\n".join(f"- {line}" for line in lines)
