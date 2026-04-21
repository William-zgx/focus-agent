from pathlib import Path


def test_local_startup_docs_describe_managed_postgres_contract():
    root = Path(__file__).resolve().parents[1]

    quickstart_text = (root / "docs" / "quick-start.md").read_text(encoding="utf-8")
    quickstart_zh_text = (root / "docs" / "quick-start.zh-CN.md").read_text(encoding="utf-8")
    local_env_text = (root / "docs" / "local.env.example").read_text(encoding="utf-8")

    assert "manage a repo-local PostgreSQL for you" in quickstart_text
    assert "PostgreSQL CLI/server tools" in quickstart_text
    assert "make api" in quickstart_text
    assert "`make api`, `make dev`" in quickstart_text
    assert "If you explicitly export `DATABASE_URI`" in quickstart_text
    assert "The raw binary does not start the managed local PostgreSQL helper for you." in quickstart_text
    assert "stops the managed database together with the service" in quickstart_text

    assert "自动管理一个 repo 内本地 PostgreSQL" in quickstart_zh_text
    assert "PostgreSQL CLI/服务端工具" in quickstart_zh_text
    assert "make api" in quickstart_zh_text
    assert "（`make api`、`make dev`、`make serve`" in quickstart_zh_text
    assert "如果你在启动前已经显式设置了 `DATABASE_URI`" in quickstart_zh_text
    assert "裸跑二进制不会帮你启动这套托管本地 PostgreSQL" in quickstart_zh_text
    assert "会随着服务一起停止并清理" in quickstart_zh_text

    assert "Leave DATABASE_URI unset when you use the local startup commands (`make api`," in local_env_text
    assert "requires PostgreSQL tools like `initdb`, `pg_ctl`," in local_env_text
    assert "explicit DATABASE_URI values are preserved" in local_env_text
