from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path
from string import Formatter
from typing import Any

import yaml

_VERSION_PATTERN = re.compile(r"^v?(\d+)(?:[._-](\d+))*$")


@dataclass(frozen=True, slots=True)
class Prompt:
    id: str
    version: str
    body: str
    variables: tuple[str, ...]
    description: str = ""


class PromptRegistry:
    def __init__(self, library_dir: str | Path | Traversable):
        self.library_dir = library_dir
        self._prompts: dict[tuple[str, str], Prompt] = {}
        self._load_library(library_dir)

    def get(self, prompt_id: str, version: str = "latest") -> Prompt:
        normalized_id = _normalize_prompt_id(prompt_id)
        normalized_version = str(version or "latest").strip()
        if normalized_version == "latest":
            candidates = [
                prompt
                for (candidate_id, _), prompt in self._prompts.items()
                if candidate_id == normalized_id
            ]
            if not candidates:
                raise KeyError(f"Unknown prompt: {normalized_id}")
            return max(candidates, key=lambda prompt: _version_sort_key(prompt.version))
        try:
            return self._prompts[(normalized_id, normalized_version)]
        except KeyError as exc:
            raise KeyError(f"Unknown prompt version: {normalized_id}@{normalized_version}") from exc

    def render(self, prompt_id: str, *, version: str = "latest", **kwargs: Any) -> str:
        prompt = self.get(prompt_id, version)
        missing = set(prompt.variables) - set(kwargs)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"Prompt {prompt.id}@{prompt.version} missing vars: {missing_text}")
        try:
            return prompt.body.format(**kwargs)
        except KeyError as exc:
            raise ValueError(
                f"Prompt {prompt.id}@{prompt.version} referenced undeclared var: {exc.args[0]}"
            ) from exc

    def list(self) -> list[Prompt]:
        return sorted(
            self._prompts.values(),
            key=lambda prompt: (prompt.id, _version_sort_key(prompt.version)),
        )

    def diff(self, prompt_id: str, old_version: str, new_version: str) -> str:
        import difflib

        old = self.get(prompt_id, old_version)
        new = self.get(prompt_id, new_version)
        return "".join(
            difflib.unified_diff(
                old.body.splitlines(keepends=True),
                new.body.splitlines(keepends=True),
                fromfile=f"{old.id}@{old.version}",
                tofile=f"{new.id}@{new.version}",
            )
        )

    def _load_library(self, library_dir: str | Path | Traversable) -> None:
        for file in _iter_prompt_files(library_dir):
            doc = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            prompt_id = _normalize_prompt_id(doc.get("id"))
            for raw_version in doc.get("versions") or ():
                if not isinstance(raw_version, dict):
                    raise ValueError(f"{file}: prompt versions must be mappings")
                version = str(raw_version.get("version") or "").strip()
                body = str(raw_version.get("body") or "")
                if not version:
                    raise ValueError(f"{file}: prompt version is required")
                if not body:
                    raise ValueError(f"{file}: prompt body is required")
                variables = tuple(raw_version.get("variables") or _template_variables(body))
                prompt = Prompt(
                    id=prompt_id,
                    version=version,
                    body=body,
                    variables=tuple(str(item) for item in variables),
                    description=str(raw_version.get("description") or doc.get("description") or ""),
                )
                key = (prompt.id, prompt.version)
                if key in self._prompts:
                    raise ValueError(f"duplicate prompt: {prompt.id}@{prompt.version}")
                self._prompts[key] = prompt


def _iter_prompt_files(library_dir: str | Path | Traversable) -> list[Any]:
    if isinstance(library_dir, (str, Path)):
        return sorted(Path(library_dir).glob("*.yaml"))
    return sorted(
        (item for item in library_dir.iterdir() if item.name.endswith(".yaml")),
        key=lambda item: item.name,
    )


def _normalize_prompt_id(value: Any) -> str:
    prompt_id = str(value or "").strip()
    if not prompt_id:
        raise ValueError("prompt id is required")
    return prompt_id


def _template_variables(body: str) -> tuple[str, ...]:
    variables: list[str] = []
    for _, field_name, _, _ in Formatter().parse(body):
        if field_name:
            variables.append(field_name.split(".", 1)[0].split("[", 1)[0])
    return tuple(dict.fromkeys(variables))


def _version_sort_key(version: str) -> tuple[Any, ...]:
    match = _VERSION_PATTERN.match(version)
    if match:
        return tuple(int(part) for part in re.findall(r"\d+", version))
    return (version,)


__all__ = ["Prompt", "PromptRegistry"]
