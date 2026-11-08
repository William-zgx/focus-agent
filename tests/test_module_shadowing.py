from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "focus_agent"


def _module_package_collisions() -> list[str]:
    collisions: list[str] = []
    for module_path in PACKAGE_ROOT.rglob("*.py"):
        if module_path.name == "__init__.py":
            continue
        package_init = module_path.with_suffix("") / "__init__.py"
        if package_init.is_file():
            collisions.append(module_path.relative_to(PROJECT_ROOT).as_posix())
    return sorted(collisions)


def test_source_tree_has_no_module_package_name_collisions() -> None:
    assert _module_package_collisions() == []


def test_public_imports_resolve_to_packages() -> None:
    expected_origins = {
        "focus_agent.services.chat": PACKAGE_ROOT / "services" / "chat" / "__init__.py",
        "focus_agent.api.routers.harness_runs": (
            PACKAGE_ROOT / "api" / "routers" / "harness_runs" / "__init__.py"
        ),
    }

    for module_name, expected_origin in expected_origins.items():
        spec = importlib.util.find_spec(module_name)
        assert spec is not None
        assert spec.submodule_search_locations is not None
        assert Path(spec.origin or "").resolve() == expected_origin.resolve()

        module = importlib.import_module(module_name)
        assert Path(module.__file__ or "").resolve() == expected_origin.resolve()
        assert hasattr(module, "__path__")
