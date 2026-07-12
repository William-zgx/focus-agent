import inspect
from pathlib import Path

import focus_agent.skills.registry as registry_module
from focus_agent.skills.models import SkillSourceDefinition
from focus_agent.skills.registry import SkillRegistry
from focus_agent.skills.registry_discovery import SkillRegistryDiscoveryMixin
from focus_agent.skills.registry_management import SkillRegistryManagementMixin


def _write_skill(root: Path, *, name: str, description: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
            ]
        ),
        encoding="utf-8",
    )


def test_skill_registry_refactor_preserves_public_method_signatures():
    registry_path = Path(registry_module.__file__)

    assert len(registry_path.read_text(encoding="utf-8").splitlines()) <= 800
    assert SkillRegistry.install_skill is SkillRegistryManagementMixin.install_skill
    assert SkillRegistry.refresh_index is SkillRegistryManagementMixin.refresh_index
    assert SkillRegistry.reload_from_settings is SkillRegistryManagementMixin.reload_from_settings
    assert SkillRegistry._discover is SkillRegistryDiscoveryMixin._discover
    assert SkillRegistry._load_skill is SkillRegistryDiscoveryMixin._load_skill
    assert SkillRegistry._source_for_path is SkillRegistryDiscoveryMixin._source_for_path
    assert SkillRegistry._source_by_id is SkillRegistryDiscoveryMixin._source_by_id

    install_parameters = inspect.signature(SkillRegistry.install_skill).parameters
    assert tuple(install_parameters) == ("self", "skill_id", "source_id", "version", "mode")
    assert install_parameters["source_id"].default == "installed"
    assert install_parameters["version"].default is None
    assert install_parameters["mode"].default == "project"
    assert tuple(inspect.signature(SkillRegistry.refresh_index).parameters) == ("self", "sources")
    assert tuple(inspect.signature(SkillRegistry.reload_from_settings).parameters) == (
        "self",
        "settings",
    )


def test_refactored_registry_preserves_external_source_safety(tmp_path):
    installed_root = tmp_path / "installed"
    source_root = tmp_path / "source"
    _write_skill(source_root, name="safe-skill", description="Visible but untrusted skill.")
    _write_skill(source_root / ".hidden", name="hidden-skill", description="Hidden skill.")
    unsafe_dir = source_root / "unsafe"
    unsafe_dir.mkdir(parents=True)
    (unsafe_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                "name: ../escape",
                "description: Unsafe path traversal skill.",
                "---",
                "",
                "# Unsafe",
            ]
        ),
        encoding="utf-8",
    )
    registry = SkillRegistry(
        [installed_root],
        source_definitions=(
            SkillSourceDefinition(
                source_id="community",
                source_type="local",
                label="Community",
                enabled=True,
                trusted=False,
                location=str(source_root),
            ),
        ),
        install_dir=installed_root,
    )

    results = registry.search_skills("", scope="all", sources=("community",), limit=10)
    rejected = registry.install_skill("safe-skill", source_id="community")
    unsafe = registry.install_skill("../escape", source_id="community")

    assert [result.skill_id for result in results] == ["safe-skill"]
    assert results[0].trust_level == "untrusted"
    assert rejected.success is False
    assert rejected.requires_review is True
    assert registry.resolve("safe-skill") is None
    assert unsafe.success is False
    assert "path separators" in str(unsafe.error)
