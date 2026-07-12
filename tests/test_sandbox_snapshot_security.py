import json

import pytest

from focus_agent.capabilities.sandbox_snapshot import _sync_workspace_snapshot


def test_workspace_snapshot_skips_all_source_symlinks_and_refreshes_them_out(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    snapshot = workspace / ".focus_agent" / "sandboxes" / "workspace"
    external = tmp_path / "external"
    external.mkdir()
    secret = external / "secret.txt"
    secret.write_text("do not expose\n", encoding="utf-8")
    internal = workspace / "inside.txt"
    internal.write_text("inside\n", encoding="utf-8")
    package = workspace / "package"
    package.mkdir()
    (package / "safe.py").write_text("safe = True\n", encoding="utf-8")
    (workspace / "external-link.txt").symlink_to(secret)
    (workspace / "internal-link.txt").symlink_to(internal)
    (package / "external-directory-link").symlink_to(external, target_is_directory=True)
    (package / "internal-file-link.txt").symlink_to(internal)
    skills = workspace / ".focus_agent" / "skills"
    skills.mkdir(parents=True)
    (skills / "external-skill-link.txt").symlink_to(secret)
    regular_then_link = workspace / "regular-then-link.txt"
    regular_then_link.write_text("regular\n", encoding="utf-8")

    _sync_workspace_snapshot(source_root=workspace, target_root=snapshot)

    assert (snapshot / "inside.txt").read_text(encoding="utf-8") == "inside\n"
    assert (snapshot / "package" / "safe.py").read_text(encoding="utf-8") == "safe = True\n"
    assert not (snapshot / "external-link.txt").exists()
    assert not (snapshot / "external-link.txt").is_symlink()
    assert not (snapshot / "internal-link.txt").exists()
    assert not (snapshot / "internal-link.txt").is_symlink()
    assert not (snapshot / "package" / "external-directory-link").exists()
    assert not (snapshot / "package" / "external-directory-link").is_symlink()
    assert not (snapshot / "package" / "internal-file-link.txt").exists()
    assert not (snapshot / "package" / "internal-file-link.txt").is_symlink()
    assert not (snapshot / ".focus_agent" / "skills" / "external-skill-link.txt").exists()
    assert not (snapshot / ".focus_agent" / "skills" / "external-skill-link.txt").is_symlink()
    assert (snapshot / "regular-then-link.txt").read_text(encoding="utf-8") == "regular\n"

    regular_then_link.unlink()
    regular_then_link.symlink_to(secret)
    _sync_workspace_snapshot(source_root=workspace, target_root=snapshot)

    manifest_path = snapshot.parent / ".focus-agent-workspace-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "external-link.txt" not in manifest
    assert "internal-link.txt" not in manifest
    assert "package/external-directory-link" not in manifest
    assert "package/internal-file-link.txt" not in manifest
    assert ".focus_agent/skills/external-skill-link.txt" not in manifest
    assert "regular-then-link.txt" not in manifest
    assert not (snapshot / "regular-then-link.txt").exists()
    assert not (snapshot / "regular-then-link.txt").is_symlink()
    assert secret.read_text(encoding="utf-8") == "do not expose\n"


def test_workspace_snapshot_replaces_target_symlink_without_following_it(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    snapshot = workspace / ".focus_agent" / "sandboxes" / "workspace"
    source_file = workspace / "safe.txt"
    source_file.write_text("before\n", encoding="utf-8")
    external = tmp_path / "external.txt"
    external.write_text("secret\n", encoding="utf-8")

    _sync_workspace_snapshot(source_root=workspace, target_root=snapshot)
    (snapshot / "safe.txt").unlink()
    (snapshot / "safe.txt").symlink_to(external)
    source_file.write_text("after\n", encoding="utf-8")

    _sync_workspace_snapshot(source_root=workspace, target_root=snapshot)

    assert (snapshot / "safe.txt").is_symlink() is False
    assert (snapshot / "safe.txt").read_text(encoding="utf-8") == "after\n"
    assert external.read_text(encoding="utf-8") == "secret\n"


def test_workspace_snapshot_rejects_symlinked_source_or_target_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.txt").write_text("safe\n", encoding="utf-8")
    external = tmp_path / "external"
    external.mkdir()
    source_link = tmp_path / "workspace-link"
    source_link.symlink_to(workspace, target_is_directory=True)
    target_link = workspace / "snapshot-link"
    target_link.symlink_to(external, target_is_directory=True)

    with pytest.raises(
        ValueError, match="workspace snapshot source must not contain symbolic links"
    ):
        _sync_workspace_snapshot(
            source_root=source_link,
            target_root=source_link / ".focus_agent" / "sandboxes" / "workspace",
        )

    with pytest.raises(
        ValueError, match="workspace snapshot target must not contain symbolic links"
    ):
        _sync_workspace_snapshot(source_root=workspace, target_root=target_link)

    with pytest.raises(
        ValueError, match="workspace snapshot target must stay inside the workspace"
    ):
        _sync_workspace_snapshot(
            source_root=workspace,
            target_root=workspace / "nested" / ".." / ".." / "outside",
        )

    assert not list(external.iterdir())
