.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND := backend
FRONTEND := frontend

.PHONY: help install install-backend install-frontend dev backend frontend test test-backend \
	test-frontend eval lint lint-backend lint-frontend typecheck typecheck-frontend lint-shell smoke clean reset-db

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install backend + frontend deps

install-backend: ## Sync the uv virtualenv
	cd $(BACKEND) && uv sync

install-frontend: ## npm install
	cd $(FRONTEND) && npm install

dev: ## Run backend + frontend together
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) backend & \
	$(MAKE) frontend & \
	wait

backend: ## Run the FastAPI backend (reload)
	cd $(BACKEND) && uv run uvicorn tinternship_backend.main:app \
		--reload --host $${BACKEND_HOST:-127.0.0.1} --port $${BACKEND_PORT:-8000}

frontend: ## Run the Vite dev server
	cd $(FRONTEND) && npm run dev

test: test-backend test-frontend ## Run both test suites

test-backend: ## Run the backend test suite (also called by CI)
	cd $(BACKEND) && uv run pytest -q

# Mounts the real route table against a fake API, so a React / React Router /
# TanStack Query bump that typechecks and builds and then paints nothing fails
# here. `tsc --noEmit` cannot see any of that.
test-frontend: ## Run the frontend test suite, vitest (also called by CI)
	cd $(FRONTEND) && npm test

eval: ## Run the agent quality evals (golden cases + rubrics)
	cd $(BACKEND) && uv run python -m tinternship_backend.evals.run

# Split in three because .github/workflows/ci.yml calls these targets rather than
# repeating the commands: its backend and frontend jobs are deliberately
# independent — a red backend must not hide a green frontend — so each needs the
# half it owns, and neither has the other's toolchain installed. `lint` is what a
# human runs and is simply all three.
#
# The point of CI calling them at all: before 2026-08-23 `ruff check src tests`,
# `pytest -q` and `npx tsc --noEmit` each existed as two identical strings, here
# and in the workflow. They had not drifted, but nothing stopped them — and the
# drift that mattered was silent in the dangerous direction: widen the ruff paths
# here, and CI would go on linting less than you do while still reporting green.
lint: lint-backend lint-frontend typecheck-frontend lint-shell ## Ruff + ESLint + tsc + shellcheck + the runtime pins
	# Python is written down in backend/.python-version and in both Dockerfile.api
	# stages, and Renovate only ever edits the last two. Divergence means CI tests
	# one interpreter while the container serves another.
	./scripts/check-runtime-pins.sh

lint-backend: ## Ruff (also called by CI)
	cd $(BACKEND) && uv run ruff check src tests

lint-frontend: ## ESLint --max-warnings 0 (also called by CI)
	cd $(FRONTEND) && npm run lint

typecheck: typecheck-frontend ## Run frontend typecheck

typecheck-frontend: ## tsc --noEmit (also called by CI)
	cd $(FRONTEND) && npm run typecheck

# CI has linted these since the workflow existed; `make lint` did not, so
# scripts/smoke.sh could be edited, run green locally, and fail the gate on the
# push — which is what happened on 2026-08-27. A local gate that checks less
# than CI is a local gate that lies.
#
# Missing shellcheck is a hard failure with the fix in the message rather than a
# skip: a check that quietly does nothing on the machine where the code is
# written is the one that was already missing.
lint-shell: ## shellcheck (also called by CI)
	@command -v shellcheck >/dev/null || { \
		echo "shellcheck is not installed, and CI will run it on this push."; \
		echo "  brew install shellcheck"; \
		exit 1; \
	}
	git ls-files '*.sh' | xargs shellcheck

# The other half of the gate: `lint` and `test` check the source, this checks
# the artifact `docker compose up -d --build` will actually publish. It is the
# only thing that exercises Chromium, the .docx round trip inside the image and
# deploy/nginx.conf — see scripts/smoke.sh. CI runs the identical script.
# The trap, not a trailing line: a nightly redeploy job runs this target in
# this checkout before it redeploys, so a run that leaves its images behind
# orphans them on the next one. `docker-cleanup` was assumed to collect them and
# cannot — they are days old and its window is 30. `make images` on its own still
# leaves them; that is what that target is for.
smoke: ## Build both images and prove they serve (slow; needs docker)
	set -e; \
	trap 'docker image rm -f tinternship-api:smoke tinternship-web:smoke >/dev/null 2>&1 || true' EXIT; \
	docker build -f deploy/Dockerfile.api -t tinternship-api:smoke .; \
	docker build -f deploy/Dockerfile.web -t tinternship-web:smoke .; \
	./scripts/smoke.sh api tinternship-api:smoke; \
	./scripts/smoke.sh web tinternship-web:smoke

reset-db: ## Delete the local SQLite database (destructive)
	rm -f data/tinternship.db data/tinternship.db-* data/traces.db data/traces.db-*
	@echo "Local database removed."

clean: ## Remove build/cache artefacts
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache $(FRONTEND)/dist
