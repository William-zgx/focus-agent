from __future__ import annotations

import pytest

from focus_agent.prompts.cli import main
from focus_agent.prompts.registry import PromptRegistry


def _write_prompt_library(tmp_path):
    prompt_file = tmp_path / "example.yaml"
    prompt_file.write_text(
        """
id: example.system
description: Example prompt.
versions:
  - version: "v1"
    body: |
      Hello {name}.
  - version: "v2"
    body: |
      Hello {name}. Use {tone}.
""".strip(),
        encoding="utf-8",
    )
    return prompt_file


def test_prompt_registry_renders_latest_and_pinned_versions(tmp_path):
    _write_prompt_library(tmp_path)

    registry = PromptRegistry(tmp_path)

    assert registry.get("example.system").version == "v2"
    assert registry.render("example.system", version="v1", name="Ada") == "Hello Ada.\n"
    assert registry.render("example.system", version="v2", name="Ada", tone="care").strip() == (
        "Hello Ada. Use care."
    )


def test_prompt_registry_reports_missing_variables(tmp_path):
    _write_prompt_library(tmp_path)
    registry = PromptRegistry(tmp_path)

    with pytest.raises(ValueError, match="missing vars: tone"):
        registry.render("example.system", version="v2", name="Ada")


def test_prompt_registry_rejects_duplicate_versions(tmp_path):
    (tmp_path / "a.yaml").write_text(
        """
id: duplicate.system
versions:
  - version: "v1"
    body: A
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        """
id: duplicate.system
versions:
  - version: "v1"
    body: B
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate prompt: duplicate.system@v1"):
        PromptRegistry(tmp_path)


def test_prompt_registry_diff_outputs_unified_diff(tmp_path):
    _write_prompt_library(tmp_path)
    registry = PromptRegistry(tmp_path)

    diff = registry.diff("example.system", "v1", "v2")

    assert "--- example.system@v1" in diff
    assert "+++ example.system@v2" in diff
    assert "+Hello {name}. Use {tone}." in diff


def test_prompt_cli_lists_and_diffs_custom_library(tmp_path, capsys):
    _write_prompt_library(tmp_path)

    assert main(["--library-dir", str(tmp_path), "list"]) == 0
    list_output = capsys.readouterr().out
    assert "example.system@v1" in list_output
    assert "example.system@v2" in list_output

    assert main(["--library-dir", str(tmp_path), "diff", "example.system", "v1", "v2"]) == 0
    diff_output = capsys.readouterr().out
    assert "--- example.system@v1" in diff_output
    assert "+++ example.system@v2" in diff_output
