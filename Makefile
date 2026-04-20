.PHONY: help venv install install-openai install-anthropic setup-local serve serve-dev serve-prod api dev test lint check ci ci-test sdk-install sdk-check sdk-build web-install web-dev web-check web-build docker-up docker-rebuild docker-restart docker-logs ui-smoke clean

UV ?= uv
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
FOCUS_AGENT_API ?= .venv/bin/focus-agent-api
CI_LOCAL_ENV_FILE ?= /tmp/focus-agent-ci-missing.env
NPM ?= npm
SDK_DIR ?= frontend-sdk
PNPM ?= pnpm
WEB_DIR ?= apps/web
DOCKER_COMPOSE ?= docker compose

help:
	@printf '%s\n' \
		'Focus Agent Make targets:' \
		'  make venv              Create .venv with uv' \
		'  make install           Install OpenAI + dev dependencies into .venv' \
		'  make install-openai    Same as install' \
		'  make install-anthropic Install Anthropic + dev dependencies into .venv' \
		'  make setup-local       Create local config files if missing' \
		'  make serve             Alias for make serve-dev' \
		'  make serve-dev         Start backend + frontend dev servers with hot reload' \
		'  make serve-prod        Build static frontend and start backend without reload' \
		'  make api               Start the API server' \
		'  make dev               Start the API server with API_RELOAD=1' \
		'  make test              Run pytest' \
		'  make lint              Run ruff check .' \
		'  make check             Run lint + test + sdk-check' \
		'  make ci                Run local CI parity checks' \
		'  make ci-test           Run pytest without repo-local env bootstrap' \
		'  make sdk-install       Install frontend SDK dependencies' \
		'  make sdk-check         Run frontend SDK type-check' \
		'  make sdk-build         Build frontend SDK' \
		'  make web-install       Install frontend workspace dependencies' \
		'  make web-dev           Start the React frontend app' \
		'  make web-check         Run frontend app type-check' \
		'  make web-build         Build the React frontend app' \
		'  make docker-up         Start the Compose service' \
		'  make docker-rebuild    Rebuild image and recreate the Compose service' \
		'  make docker-restart    Restart the running Compose service' \
		'  make docker-logs       Follow Compose service logs' \
		'  make ui-smoke          Run the real-browser UI smoke test' \
		'  make clean             Remove Python/pytest caches'

.venv/bin/python:
	$(UV) venv

venv: .venv/bin/python

install: install-openai

install-openai: .venv/bin/python
	$(UV) pip install -e '.[openai,dev]'

install-anthropic: .venv/bin/python
	$(UV) pip install -e '.[anthropic,dev]'

setup-local:
	@test -f .env || cp .env.example .env
	@mkdir -p .focus_agent
	@test -f .focus_agent/local.env || cp docs/local.env.example .focus_agent/local.env
	@test -f .focus_agent/models.toml || cp docs/models.example.toml .focus_agent/models.toml
	@test -f .focus_agent/tools.toml || cp docs/tools.example.toml .focus_agent/tools.toml
	@printf '%s\n' 'Local config files are ready.'

serve:
	./scripts/serve-dev.sh

serve-dev:
	./scripts/serve-dev.sh

serve-prod:
	./scripts/serve-prod.sh

api: .venv/bin/python
	SERVE_SCRIPT_NAME=api ./scripts/run-api.sh

dev: .venv/bin/python
	SERVE_SCRIPT_NAME=dev API_RELOAD=1 ./scripts/run-api.sh

test: .venv/bin/python
	$(PYTEST)

lint: .venv/bin/python
	$(RUFF) check .

check: lint test sdk-check

ci: lint ci-test sdk-check sdk-build

ci-test: .venv/bin/python
	FOCUS_AGENT_LOCAL_ENV_FILE=$(CI_LOCAL_ENV_FILE) $(PYTEST)

$(SDK_DIR)/node_modules:
	cd $(SDK_DIR) && $(NPM) install

sdk-install: $(SDK_DIR)/node_modules

sdk-check: $(SDK_DIR)/node_modules
	cd $(SDK_DIR) && $(NPM) run check

sdk-build: $(SDK_DIR)/node_modules
	cd $(SDK_DIR) && $(NPM) run build

node_modules:
	$(PNPM) install --registry=https://registry.npmjs.org

web-install: node_modules

web-dev: node_modules
	$(PNPM) --filter @focus-agent/web-app dev

web-check: node_modules
	$(PNPM) web:check

web-build: node_modules
	$(PNPM) web:build

docker-up:
	$(DOCKER_COMPOSE) up -d focus-agent

docker-rebuild:
	$(DOCKER_COMPOSE) up -d --build focus-agent

docker-restart:
	$(DOCKER_COMPOSE) restart focus-agent

docker-logs:
	$(DOCKER_COMPOSE) logs -f focus-agent

ui-smoke: .venv/bin/python
	$(PYTHON) scripts/ui_smoke_test.py

clean:
	rm -rf .pytest_cache
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
