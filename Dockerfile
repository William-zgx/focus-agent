ARG NODE_IMAGE=mcr.microsoft.com/devcontainers/javascript-node:1-20-bookworm
ARG PYTHON_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.11-bookworm
ARG NPM_REGISTRY=https://mirrors.tuna.tsinghua.edu.cn/npm/
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_DEFAULT_TIMEOUT=120

FROM ${NODE_IMAGE} AS frontend-builder

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

WORKDIR /workspace

RUN corepack enable
RUN pnpm config set registry "${NPM_REGISTRY}"

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend-sdk/package.json frontend-sdk/package.json
COPY apps/web/package.json apps/web/package.json

RUN pnpm install --frozen-lockfile

COPY frontend-sdk ./frontend-sdk
COPY apps/web ./apps/web

RUN pnpm web:build

FROM ${PYTHON_IMAGE} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    API_RELOAD=0 \
    WEB_APP_DIST_DIR=/app/apps/web/dist \
    WEB_APP_DEV_SERVER_URL= \
    FOCUS_AGENT_DATA_DIR=/data \
    FOCUS_AGENT_LOCAL_ENV_FILE=/data/local.env \
    FOCUS_AGENT_MODEL_CATALOG_DOC=/data/models.toml \
    FOCUS_AGENT_TOOL_CATALOG_DOC=/data/tools.toml \
    BRANCH_DB_PATH=/data/branches.sqlite3 \
    ARTIFACT_DIR=/data/artifacts \
    LOCAL_CHECKPOINT_PATH=/data/langgraph-checkpoints.pkl \
    LOCAL_STORE_PATH=/data/langgraph-store.pkl

WORKDIR /app

RUN addgroup --system focusagent \
    && adduser --system --ingroup focusagent --home /home/focusagent focusagent

COPY pyproject.toml README.md README.zh-CN.md LICENSE ./
COPY src ./src

RUN printf 'ddgs==9.14.0\nlxml==6.1.0\n' > /tmp/docker-constraints.txt \
    && pip install --no-cache-dir -c /tmp/docker-constraints.txt ".[openai,anthropic]" \
    && rm -f /tmp/docker-constraints.txt

COPY --from=frontend-builder /workspace/apps/web/dist /app/apps/web/dist
COPY docs/local.env.example /opt/focus-agent/defaults/local.env
COPY docs/models.example.toml /opt/focus-agent/defaults/models.toml
COPY docs/tools.example.toml /opt/focus-agent/defaults/tools.toml
COPY docker/entrypoint.sh /entrypoint.sh

RUN mkdir -p /data/artifacts /app/apps/web \
    && cp /opt/focus-agent/defaults/local.env /data/local.env \
    && cp /opt/focus-agent/defaults/models.toml /data/models.toml \
    && cp /opt/focus-agent/defaults/tools.toml /data/tools.toml \
    && chmod +x /entrypoint.sh \
    && chown -R focusagent:focusagent /app /data /home/focusagent /opt/focus-agent /entrypoint.sh

USER focusagent

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["focus-agent-api"]
