from pathlib import Path


def test_containerization_artifacts_exist_and_wire_prod_runtime():
    root = Path(__file__).resolve().parents[1]

    required = [
        root / "Dockerfile",
        root / ".dockerignore",
        root / "compose.yaml",
        root / "compose.prod.yaml",
        root / "docker" / "entrypoint.sh",
    ]

    for path in required:
        assert path.exists(), f"missing {path}"

    dockerfile_text = (root / "Dockerfile").read_text(encoding="utf-8")
    assert 'ARG NODE_IMAGE=' in dockerfile_text
    assert 'ARG PYTHON_IMAGE=' in dockerfile_text
    assert 'ARG NPM_REGISTRY=' in dockerfile_text
    assert 'ARG PIP_INDEX_URL=' in dockerfile_text
    assert "FROM ${NODE_IMAGE} AS frontend-builder" in dockerfile_text
    assert "FROM ${PYTHON_IMAGE} AS runtime" in dockerfile_text
    assert "pnpm web:build" in dockerfile_text
    assert 'pip install --no-cache-dir -c /tmp/docker-constraints.txt ".[openai,anthropic]"' in dockerfile_text
    assert 'ENTRYPOINT ["/entrypoint.sh"]' in dockerfile_text
    assert 'CMD ["focus-agent-api"]' in dockerfile_text
    assert "FOCUS_AGENT_LOCAL_ENV_FILE=/data/local.env" in dockerfile_text

    entrypoint_text = (root / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert "copy_if_missing" in entrypoint_text
    assert 'FOCUS_AGENT_LOCAL_ENV_FILE="${FOCUS_AGENT_LOCAL_ENV_FILE:-$DATA_DIR/local.env}"' in entrypoint_text
    assert 'BRANCH_DB_PATH="${BRANCH_DB_PATH:-$DATA_DIR/branches.sqlite3}"' in entrypoint_text
    assert 'LOCAL_CHECKPOINT_PATH="${LOCAL_CHECKPOINT_PATH:-$DATA_DIR/langgraph-checkpoints.pkl}"' in entrypoint_text
    assert 'exec "$@"' in entrypoint_text

    compose_text = (root / "compose.yaml").read_text(encoding="utf-8")
    assert "postgres:" in compose_text
    assert "depends_on:" in compose_text
    assert '${FOCUS_AGENT_DATA_MOUNT:-focus_agent_data}:/data' in compose_text
    assert '${FOCUS_AGENT_PGDATA_MOUNT:-focus_agent_pgdata}:/var/lib/postgresql/data' in compose_text
    assert 'AUTH_DEMO_TOKENS_ENABLED: ${FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED:-true}' in compose_text
    assert 'MODEL: ${FOCUS_AGENT_MODEL:-}' in compose_text
    assert 'OPENAI_API_KEY:' not in compose_text
    assert 'ANTHROPIC_API_KEY:' not in compose_text
    assert 'TAVILY_API_KEY:' not in compose_text
    assert "FOCUS_AGENT_DATABASE_URI" in compose_text
    assert "pg_isready" in compose_text
    assert "FOCUS_AGENT_PIP_INDEX_URL" in compose_text
    assert "/healthz" in compose_text

    compose_prod_text = (root / "compose.prod.yaml").read_text(encoding="utf-8")
    assert "FOCUS_AGENT_IMAGE" in compose_prod_text
    assert "FOCUS_AGENT_DATABASE_URI" in compose_prod_text
    assert "AUTH_DEMO_TOKENS_ENABLED: ${FOCUS_AGENT_AUTH_DEMO_TOKENS_ENABLED:-false}" in compose_prod_text
    assert "postgres:" not in compose_prod_text


def test_containerization_docs_explain_current_boundary():
    root = Path(__file__).resolve().parents[1]

    readme_text = (root / "README.md").read_text(encoding="utf-8")
    readme_zh_text = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    architecture_text = (root / "docs" / "architecture.md").read_text(encoding="utf-8")
    roadmap_text = (root / "docs" / "roadmap.md").read_text(encoding="utf-8")
    deployment_text = (root / "docs" / "docker-deployment.md").read_text(encoding="utf-8")

    assert "docker compose up --build" in readme_text
    assert "FOCUS_AGENT_DATABASE_URI" in readme_text
    assert "compose.prod.yaml" in readme_text
    assert "docker compose up --build" in readme_zh_text
    assert "Postgres" in readme_zh_text
    assert "compose.prod.yaml" in readme_zh_text
    assert "Docker / Compose 部署" in architecture_text
    assert "compose.prod.yaml" in architecture_text
    assert "compose.yaml" in roadmap_text
    assert "compose.prod.yaml" in roadmap_text
    assert "Docker 部署已分层" in roadmap_text
    assert "本地 Docker 联调" in deployment_text
    assert "生产/预发部署" in deployment_text
