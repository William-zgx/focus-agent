from pathlib import Path


def test_ui_smoke_script_matches_bilingual_web_app_flow():
    root = Path(__file__).resolve().parents[1]
    script_text = (root / "scripts" / "ui_smoke_test.py").read_text(encoding="utf-8")

    assert 'DEFAULT_APP_URL = "http://127.0.0.1:8000/app"' in script_text
    assert "newConversationLabels = ['New', 'New conversation', '新建', '新建对话']" in script_text
    assert "newBranchLabels = ['Fork branch', 'New branch', '新建分支', '创建分支']" in script_text
    assert "createBranchLabels = ['Create branch', '创建分支']" in script_text
    assert "sendLabels = ['Send', 'Send message', '发送', '发送消息']" in script_text
    assert "proposalLabels = ['Generate conclusion', '生成带回结论']" in script_text
    assert "mergeFormLabels = ['Summary', '摘要']" in script_text
    assert "collect_browser_diagnostics" in script_text
