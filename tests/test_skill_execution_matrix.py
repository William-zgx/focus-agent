from __future__ import annotations

import json
import subprocess
from pathlib import Path

from focus_agent.skills.registry import SkillRegistry

ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".focus_agent" / "skills"
MATRIX_PATH = ROOT / "docs" / "skill-execution-matrix.json"
ALLOWED_CATEGORIES = {
    "prompt_only",
    "script_offline",
    "script_network",
    "host_control",
    "document_generation",
}


def _matrix() -> list[dict[str, object]]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def _tracked_skill_ids() -> set[str]:
    completed = subprocess.run(
        ["git", "ls-files", ".focus_agent/skills/*/SKILL.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {Path(line).parent.name for line in completed.stdout.splitlines() if line.strip()}


def test_skill_execution_matrix_covers_all_tracked_skills() -> None:
    matrix = _matrix()
    matrix_ids = {str(item["skill_id"]) for item in matrix}
    tracked_skill_ids = _tracked_skill_ids()

    assert tracked_skill_ids <= matrix_ids
    assert len(matrix) == len(matrix_ids)


def test_skill_execution_matrix_categories_and_paths_are_explicit() -> None:
    for item in _matrix():
        assert item["category"] in ALLOWED_CATEGORIES
        assert str(item["execution_path"]).strip()
        assert str(item["smoke_case"]).strip()
        assert isinstance(item["has_script_entrypoint"], bool)
        assert isinstance(item["host_control"], bool)
        if item["category"] == "host_control":
            assert item["host_control"] is True
            assert str(item["execution_path"]).startswith("broker:")


def test_script_skills_have_declared_entrypoints() -> None:
    registry = SkillRegistry([SKILLS_ROOT])
    by_id = {str(skill["name"]): skill for skill in registry.list_skills()}

    for item in _matrix():
        skill_id = str(item["skill_id"])
        if skill_id not in _tracked_skill_ids() or not item["has_script_entrypoint"]:
            continue
        entrypoint_name = str(item["execution_path"]).split("entrypoint:", 1)[1]
        skill = by_id[skill_id]
        names = {str(entrypoint["name"]) for entrypoint in skill["entrypoints"]}
        assert entrypoint_name in names


def test_host_control_skills_do_not_use_general_entrypoints() -> None:
    registry = SkillRegistry([SKILLS_ROOT])
    by_id = {str(skill["name"]): skill for skill in registry.list_skills()}

    for item in _matrix():
        skill_id = str(item["skill_id"])
        if skill_id in _tracked_skill_ids() and item["host_control"]:
            assert not by_id[skill_id]["entrypoints"]
