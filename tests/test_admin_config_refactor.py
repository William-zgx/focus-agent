from __future__ import annotations

from pathlib import Path

import pytest

from focus_agent.api.contract_models.admin_config import AdminModelProviderConfigPayload
from focus_agent.config import ProviderConfig
from focus_agent.services import admin_config, admin_config_io, admin_config_rendering


def test_admin_config_reexports_extracted_helpers() -> None:
    rendering_helpers = (
        "_provider_payloads",
        "_provider_api_key_default",
        "_model_payloads",
        "_render_model_catalog_toml",
        "_render_tool_catalog_toml",
        "_tool_payload_from_current",
        "_merge_tool_payload",
        "_field_or_existing",
        "_dataclass_values",
        "_append_toml_key",
        "_toml_value",
        "_toml_bare_or_quoted_key",
        "_coerce_config_value",
    )
    io_helpers = (
        "_write_local_env_updates",
        "_format_env_value",
        "_write_text_atomic",
        "_settings_env",
        "_configured_env_value",
        "_model_catalog_path",
        "_tool_catalog_path",
        "_local_env_path",
        "_source_response",
        "_path_writable",
    )

    for name in rendering_helpers:
        assert getattr(admin_config, name) is getattr(admin_config_rendering, name)
    for name in io_helpers:
        assert getattr(admin_config, name) is getattr(admin_config_io, name)


def test_provider_payload_merge_still_drops_and_rejects_sensitive_defaults() -> None:
    existing = ProviderConfig(
        id="openai",
        api_key_env="OPENAI_API_KEY",
        api_key_default="sk-existing-secret",
    )

    merged = admin_config._provider_payloads(None, (existing,))

    assert merged[0].api_key_default is None
    assert existing.api_key_default == "sk-existing-secret"

    payload = AdminModelProviderConfigPayload(
        id="openai",
        api_key_env="OPENAI_API_KEY",
        api_key_default="sk-new-secret",
    )
    with pytest.raises(admin_config.AdminConfigError, match="api_key_default"):
        admin_config._provider_payloads([payload], ())


def test_local_env_update_keeps_atomic_replace_and_existing_content(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "config" / "local.env"
    path.parent.mkdir()
    path.write_text("# keep\nKEEP=value\nFLAG=false\nREMOVE=old\n", encoding="utf-8")
    tmp_file = path.with_name(f".{path.name}.tmp")
    tmp_file.write_text("stale temporary content", encoding="utf-8")
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def record_replace(source: Path, target: Path) -> Path:
        replace_calls.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", record_replace)

    admin_config._write_local_env_updates(
        path,
        {"FLAG": True, "REMOVE": None, "ADDED": 3},
    )

    assert path.read_text(encoding="utf-8") == (
        "# keep\nKEEP=value\nFLAG=true\n\nADDED=3\n"
    )
    assert replace_calls == [(tmp_file, path)]
    assert not tmp_file.exists()
