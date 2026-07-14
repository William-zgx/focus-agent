ARG BASE_IMAGE=node:20-bookworm-slim
ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

FROM ${BASE_IMAGE}

ARG APT_MIRROR=
ARG APT_SECURITY_MIRROR=
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=120

ENV DEBIAN_FRONTEND=noninteractive \
    COREPACK_NPM_REGISTRY=${NPM_REGISTRY} \
    COREPACK_HOME=/pnpm/corepack \
    PNPM_HOME=/pnpm \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
ENV PATH="${PNPM_HOME}:${PATH}"

USER root

RUN if [ -n "${APT_MIRROR}" ]; then \
        find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) \
            -exec sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g" {} +; \
    fi \
    && if [ -n "${APT_SECURITY_MIRROR}" ]; then \
        find /etc/apt -type f \( -name "*.list" -o -name "*.sources" \) \
            -exec sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" {} +; \
    fi \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cargo \
        curl \
        g++ \
        gcc \
        git \
        golang-go \
        make \
        pkg-config \
        python-is-python3 \
        python3 \
        python3-pip \
        python3-venv \
        rustc \
    && rm -rf /var/lib/apt/lists/*

RUN npm config set registry "${NPM_REGISTRY}" \
    && if command -v corepack >/dev/null 2>&1; then \
        corepack enable pnpm \
        && corepack install --global pnpm@9.15.9; \
    else \
        npm install -g pnpm@9.15.9; \
    fi \
    && chmod -R a+rX "${PNPM_HOME}" \
    && pip_flags="" \
    && if python3 -m pip install --help | grep -q -- "--break-system-packages"; then \
        pip_flags="--break-system-packages"; \
    fi \
    && python3 -m pip install --no-cache-dir ${pip_flags} \
        --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir ${pip_flags} \
        "pytest==8.3.2" \
        "ruff==0.15.10" \
        "mypy==1.13.0"

RUN mkdir -p /workspace /workspace_input /sandbox_output /sandbox_cache /tmp \
    && chmod 0777 /workspace /workspace_input /sandbox_output /sandbox_cache /tmp

WORKDIR /workspace

CMD ["python3", "--version"]
