from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .registry import Prompt, PromptRegistry


@lru_cache(maxsize=1)
def get_registry(library_dir: str | Path | None = None) -> PromptRegistry:
    if library_dir is None:
        resource = files("focus_agent.prompts").joinpath("library")
        return PromptRegistry(resource)
    return PromptRegistry(Path(library_dir))


__all__ = ["Prompt", "PromptRegistry", "get_registry"]
