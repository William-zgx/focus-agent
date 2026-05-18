import json
from pathlib import Path


def test_quality_gate_scaffold_exposes_opt_in_stricter_checks():
    root = Path(__file__).resolve().parents[1]
    root_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    web_package = json.loads((root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")

    root_scripts = root_package["scripts"]
    web_scripts = web_package["scripts"]

    assert root_scripts["web:lint:full"] == "pnpm --filter @focus-agent/web-app lint:full"
    assert (
        root_scripts["web:format:check:full"]
        == "pnpm --filter @focus-agent/web-app format:check:full"
    )
    assert web_scripts["lint:full"] == "pnpm dlx @biomejs/biome@2.2.4 lint src"
    assert web_scripts["format:check:full"] == "pnpm dlx @biomejs/biome@2.2.4 format src"

    assert "lint-strict" in root_scripts["check"]
    assert "web:lint:full" in root_scripts["check"]
    assert "web:format:check:full" in root_scripts["check"]
    check_dependencies = _make_target_dependencies(makefile_text, "check")
    assert "lint-strict" in check_dependencies
    assert "frontend-check-full" in check_dependencies
    assert "web-lint" not in check_dependencies
    assert "web-format-check" not in check_dependencies
    ci_dependencies = _make_target_dependencies(makefile_text, "ci")
    assert "lint-strict" in ci_dependencies
    assert "frontend-check-full" in ci_dependencies
    assert "web-lint" not in ci_dependencies
    assert "web-format-check" not in ci_dependencies

    assert "lint-strict:" in makefile_text
    assert "$(RUFF) check --extend-select I,W,UP,N ." in makefile_text
    assert "web-lint-full:" in makefile_text
    assert "web-format-check-full:" in makefile_text
    assert "frontend-check-full:" in makefile_text


def _make_target_dependencies(makefile_text: str, target: str) -> list[str]:
    for line in makefile_text.splitlines():
        prefix = f"{target}:"
        if line.startswith(prefix):
            return line.removeprefix(prefix).split()
    raise AssertionError(f"missing Make target: {target}")
