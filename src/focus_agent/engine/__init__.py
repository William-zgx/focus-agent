"""Runtime and graph orchestration for Focus Agent."""

from .runtime import AppRuntime, create_runtime


def build_graph(*args: object, **kwargs: object) -> object:
    from .graph_builder import build_graph as graph_builder

    return graph_builder(*args, **kwargs)


__all__ = [
    "AppRuntime",
    "build_graph",
    "create_runtime",
]
