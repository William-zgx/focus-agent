.PHONY: help venv install install-openai install-anthropic setup-local serve serve-dev serve-prod api dev test test-graph-builder test-chat-service test-thread-stream-frontend-regressions lint lint-strict import-sort-check format format-check check ci ci-test contract-check openapi-export sdk-generate-types sdk-openapi-types-check architecture-report compat-report release-gate release-evidence ci-release-gate ci-release-evidence nightly-regression feedback-regression production-smoke postgres-ops otel-smoke agent-governance-report sdk-install sdk-check sdk-build sdk-validate-transport web-install web-dev web-check web-build web-lint web-lint-full web-format web-format-check web-format-check-full frontend-check frontend-check-full frontend-style-check frontend-android-runtime-smoke frontend-bundle-check frontend-qa frontend-visual-qa frontend-build docker-up docker-rebuild docker-restart docker-logs ui-smoke ui-smoke-observability ui-smoke-productivity ui-smoke-agent-team-adoption clean

UV ?= uv
PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
PYTEST ?= .venv/bin/pytest
RUFF ?= .venv/bin/ruff
FOCUS_AGENT_API ?= .venv/bin/focus-agent-api
CI_LOCAL_ENV_FILE ?= /tmp/focus-agent-ci-missing.env
SDK_DIR ?= frontend-sdk
PNPM ?= pnpm
PNPM_INSTALL_FLAGS ?= --frozen-lockfile --registry=https://registry.npmjs.org
WEB_DIR ?= apps/web
FRONTEND_QA_BASE_URL ?= http://127.0.0.1:5173
FRONTEND_QA_ROUTES ?= /,/admin/config,/c/local-thread-0001/t/local-thread-0001
FRONTEND_QA_SCHEMES ?= dark
FRONTEND_QA_VIEWPORT ?= 390,844
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
		'  make test-graph-builder Run graph builder tests' \
		'  make test-chat-service Run chat service tests' \
		'  make test-thread-stream-frontend-regressions Run Node stream frontend regression tests' \
		'  make lint              Run ruff check .' \
		'  make lint-strict       Run stricter Ruff checks' \
		'  make import-sort-check Run Ruff import sorting check' \
		'  make format            Run ruff format .' \
		'  make format-check      Check ruff formatting without writing changes' \
		'  make check             Run lint + test + contract-check + SDK/Web checks' \
		'  make ci                Run local CI parity checks' \
		'  make ci-test           Run pytest without repo-local env bootstrap' \
		'  make contract-check    Verify API and frontend SDK contract snapshots' \
		'  make architecture-report Report large files and import boundary signals without gating CI' \
		'  make compat-report     Report explicit legacy/compatibility inventory signals' \
		'  make release-gate      Run the full release gate and write reports/release-gate/latest.json' \
		'  make release-evidence  Generate a production release evidence manifest' \
		'  make ci-release-gate   Run the CI release gate entrypoint' \
		'  make ci-release-evidence Generate CI release evidence manifest' \
		'  make nightly-regression Generate reports/nightly/latest.json' \
		'  make feedback-regression Generate reports/nightly/feedback-regression.json' \
		'  make production-smoke  Generate reports/release-gate/production-smoke.json' \
		'  make sdk-install       Install frontend SDK dependencies' \
		'  make sdk-check         Run frontend SDK type-check' \
		'  make sdk-build         Build frontend SDK' \
		'  make sdk-validate-transport Run frontend SDK transport validation' \
		'  make web-install       Install frontend workspace dependencies' \
		'  make web-dev           Start the React frontend app' \
		'  make web-check         Run frontend app type-check' \
		'  make web-build         Build the React frontend app' \
		'  make web-lint          Run Web Biome lint on the enabled scope' \
		'  make web-lint-full     Run Web Biome lint on all app src' \
		'  make web-format        Run Web Biome format write on the enabled scope' \
		'  make web-format-check  Check Web Biome format on the enabled scope' \
		'  make web-format-check-full Check Web Biome format on all app src' \
		'  make frontend-check    Run frontend SDK and Web checks' \
		'  make frontend-check-full Run full-scope frontend checks' \
		'  make frontend-qa       Run full frontend checks, style governance, architecture, and Android runtime smoke' \
		'  make frontend-visual-qa Run visual and a11y baselines against FRONTEND_QA_BASE_URL' \
		'  make frontend-build    Build frontend SDK and Web app' \
		'  make docker-up         Start the Compose service' \
		'  make docker-rebuild    Rebuild image and recreate the Compose service' \
		'  make docker-restart    Restart the running Compose service' \
		'  make docker-logs       Follow Compose service logs' \
		'  make ui-smoke          Run the real-browser chat and branch UI smoke test' \
		'  make ui-smoke-observability Run the real-browser observability UI smoke test' \
		'  make ui-smoke-productivity Run the productivity source-level UI smoke test' \
		'  make ui-smoke-agent-team-adoption Run the Agent Team adoption UI smoke test' \
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

test-graph-builder: .venv/bin/python
	$(PYTEST) tests/test_graph_builder.py

test-chat-service: .venv/bin/python
	$(PYTEST) tests/test_chat_service.py

test-thread-stream-frontend-regressions: node_modules
	node --test tests/test_thread_stream_frontend_regressions.mjs

lint: .venv/bin/python
	$(RUFF) check .

lint-strict: .venv/bin/python
	$(RUFF) check --extend-select I,W,UP,N .

import-sort-check: .venv/bin/python
	$(RUFF) check --select I .

format: .venv/bin/python
	$(RUFF) format .

format-check: .venv/bin/python
	$(RUFF) format --check .

check: lint-strict test contract-check frontend-check-full sdk-build web-build test-thread-stream-frontend-regressions

ci: lint-strict ci-test contract-check frontend-check-full sdk-build web-build test-thread-stream-frontend-regressions

ci-test: .venv/bin/python
	FOCUS_AGENT_LOCAL_ENV_FILE=$(CI_LOCAL_ENV_FILE) $(PYTEST)

contract-check: .venv/bin/python
	$(PYTHON) scripts/check_contracts.py

openapi-export: .venv/bin/python
	$(PYTHON) scripts/export-openapi.py

sdk-generate-types: node_modules .venv/bin/python
	./scripts/generate-sdk-types.sh

sdk-openapi-types-check: node_modules .venv/bin/python
	./scripts/generate-sdk-types.sh
	git diff --exit-code docs/api/openapi.json $(SDK_DIR)/src/types/__generated__.ts

architecture-report: .venv/bin/python
	$(PYTHON) scripts/architecture_report.py $(ARCHITECTURE_REPORT_ARGS)

compat-report: .venv/bin/python
	$(PYTHON) scripts/compat_report.py $(COMPAT_REPORT_ARGS)

release-gate: .venv/bin/python
	$(PYTHON) scripts/release_gate.py $(RELEASE_GATE_ARGS)

release-evidence: .venv/bin/python
	$(PYTHON) scripts/release_evidence.py $(RELEASE_EVIDENCE_ARGS)

ci-release-gate: .venv/bin/python
	$(PYTHON) scripts/release_gate.py $(CI_RELEASE_GATE_ARGS)

ci-release-evidence: .venv/bin/python
	$(PYTHON) scripts/release_evidence.py $(CI_RELEASE_EVIDENCE_ARGS)

nightly-regression: .venv/bin/python
	@mkdir -p reports/release-gate reports/nightly
	$(PYTHON) scripts/memory_context_eval.py --report-json reports/release-gate/memory-context-eval.json
	$(PYTHON) scripts/memory_context_eval.py --trend-report-json reports/release-gate/memory-context-trend.json
	$(PYTHON) scripts/feedback_regression.py $(FEEDBACK_REGRESSION_ARGS)
	$(PYTHON) scripts/nightly_regression.py $(NIGHTLY_REGRESSION_ARGS)

feedback-regression: .venv/bin/python
	@mkdir -p reports/nightly
	$(PYTHON) scripts/feedback_regression.py $(FEEDBACK_REGRESSION_ARGS)

production-smoke: .venv/bin/python
	$(PYTHON) scripts/production_smoke.py $(PRODUCTION_SMOKE_ARGS)

postgres-ops: .venv/bin/python
	$(PYTHON) scripts/postgres_ops.py $(POSTGRES_OPS_ARGS)

otel-smoke: .venv/bin/python
	$(PYTHON) scripts/otel_smoke.py $(OTEL_SMOKE_ARGS)

agent-governance-report: .venv/bin/python
	$(PYTHON) scripts/agent_governance_report.py $(AGENT_GOVERNANCE_REPORT_ARGS)

sdk-install: node_modules

sdk-check: node_modules
	$(PNPM) --filter @focus-agent/web-sdk check

sdk-build: node_modules
	$(PNPM) --filter @focus-agent/web-sdk build

sdk-validate-transport: node_modules
	$(PNPM) --filter @focus-agent/web-sdk validate:transport
	@rm -rf $(SDK_DIR)/dist-validation

node_modules: package.json pnpm-lock.yaml pnpm-workspace.yaml $(SDK_DIR)/package.json $(WEB_DIR)/package.json
	$(PNPM) install $(PNPM_INSTALL_FLAGS)

web-install: node_modules

web-dev: node_modules
	$(PNPM) --filter @focus-agent/web-app dev

web-check: node_modules
	$(PNPM) web:check

web-build: node_modules
	$(PNPM) web:build

web-lint: node_modules
	$(PNPM) --filter @focus-agent/web-app lint

web-lint-full: node_modules
	$(PNPM) web:lint:full

web-format: node_modules
	$(PNPM) --filter @focus-agent/web-app format

web-format-check: node_modules
	$(PNPM) --filter @focus-agent/web-app format:check

web-format-check-full: node_modules
	$(PNPM) web:format:check:full

frontend-check: sdk-check sdk-validate-transport web-lint web-format-check web-check

frontend-check-full: sdk-check sdk-validate-transport web-lint-full web-format-check-full web-check

frontend-style-check: node_modules
	$(PNPM) --filter @focus-agent/web-app style:check

frontend-android-runtime-smoke: node_modules
	$(PNPM) --filter @focus-agent/web-app smoke:android-local-runtime

frontend-bundle-check: web-build
	$(PNPM) --filter @focus-agent/web-app bundle:check

frontend-qa: frontend-check-full frontend-style-check frontend-android-runtime-smoke frontend-bundle-check architecture-report compat-report

frontend-visual-qa: node_modules
	$(PNPM) --filter @focus-agent/web-app visual:baseline -- --base-url $(FRONTEND_QA_BASE_URL) --routes $(FRONTEND_QA_ROUTES) --schemes $(FRONTEND_QA_SCHEMES) --viewport $(FRONTEND_QA_VIEWPORT)
	$(PNPM) --filter @focus-agent/web-app a11y:baseline -- --base-url $(FRONTEND_QA_BASE_URL) --routes $(FRONTEND_QA_ROUTES) --fail-on-violations

frontend-build: sdk-build web-build

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

ui-smoke-observability: .venv/bin/python
	$(PYTHON) scripts/observability_ui_smoke.py

ui-smoke-productivity: node_modules
	$(PNPM) --dir $(WEB_DIR) smoke:productivity

ui-smoke-agent-team-adoption: node_modules
	$(PNPM) --dir $(WEB_DIR) smoke:agent-team-adoption

clean:
	rm -rf .pytest_cache
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
