from pathlib import Path


def test_ui_smoke_script_matches_bilingual_web_app_flow():
    root = Path(__file__).resolve().parents[1]
    script_text = (root / "scripts" / "ui_smoke_test.py").read_text(encoding="utf-8")

    assert 'DEFAULT_APP_URL = "http://127.0.0.1:5173/app/"' in script_text
    assert "newConversationLabels = ['New', 'New conversation', '新建', '新建对话']" in script_text
    assert "newBranchLabels = ['Fork branch', 'New branch', '新建分支', '创建分支']" in script_text
    assert "create branch dialog" not in script_text
    assert "sendLabels = ['Send', 'Send message', '发送', '发送消息']" in script_text
    assert "proposalLabels = ['Generate conclusion', '生成带回结论']" in script_text
    assert "mergeFormLabels = ['Summary', '摘要']" in script_text
    assert "DEFAULT_RESPONSE_TIMEOUT_SECONDS = 180.0" in script_text
    assert "--response-timeout-seconds" in script_text
    assert "stableAssistantResponseTimeoutMs" in script_text
    assert "response_timeout_seconds + 300.0" in script_text
    assert "collect_browser_diagnostics" in script_text


def test_productivity_smoke_script_reports_expected_routes():
    root = Path(__file__).resolve().parents[1]
    script_text = (root / "apps" / "web" / "scripts" / "productivity-smoke.mjs").read_text(
        encoding="utf-8"
    )
    package_text = (root / "apps" / "web" / "package.json").read_text(encoding="utf-8")
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")

    assert '"/app/productivity/notes"' in script_text
    assert '"/app/productivity/tasks"' in script_text
    assert "reports/ui-smoke/productivity.json" in script_text
    assert '"smoke:productivity": "node ./scripts/productivity-smoke.mjs"' in package_text
    assert "ui-smoke-productivity:" in makefile_text
    assert "$(PNPM) --dir $(WEB_DIR) smoke:productivity" in makefile_text


def test_agent_team_adoption_smoke_command_is_reserved_for_web_worker():
    root = Path(__file__).resolve().parents[1]
    makefile_text = (root / "Makefile").read_text(encoding="utf-8")

    assert "ui-smoke-agent-team-adoption:" in makefile_text
    assert "$(PNPM) --dir $(WEB_DIR) smoke:agent-team-adoption" in makefile_text
