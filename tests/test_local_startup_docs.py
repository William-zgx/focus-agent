from pathlib import Path


def test_local_startup_docs_describe_managed_postgres_contract():
    root = Path(__file__).resolve().parents[1]

    readme_text = (root / "README.md").read_text(encoding="utf-8")
    readme_zh_text = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    local_env_text = (root / "docs" / "local.env.example").read_text(encoding="utf-8")

    assert "manage a repo-local PostgreSQL for you" in readme_text
    assert "`make api`, `make dev`" in readme_text
    assert "If you explicitly export `DATABASE_URI`" in readme_text
    assert "stop the managed database together with the service" in readme_text

    assert "自动管理一个 repo 内本地 PostgreSQL" in readme_zh_text
    assert "（`make api`、`make dev`、`make serve`" in readme_zh_text
    assert "如果你在启动前已经显式设置了 `DATABASE_URI`" in readme_zh_text
    assert "会随着服务一起停止并清理" in readme_zh_text

    assert "Leave DATABASE_URI unset when you use the local startup commands (`make api`," in local_env_text
    assert "explicit DATABASE_URI values are preserved" in local_env_text
