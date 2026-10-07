.DEFAULT_GOAL := help
SHELL := /bin/bash

# The gate, as targets .github/workflows/ci.yml CALLS rather than repeats — and
# that a deployment's nightly redeploy can call too (`make smoke`, which needs
# only docker). One definition per command: two copies drift, silently and in
# the dangerous direction. → documentation/verification.md

BACKEND := app/backend

.PHONY: help install dev seed seed-check lint typecheck test build public verify app-test smoke sync

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-11s\033[0m %s\n", $$1, $$2}'

install: ## Install the demo's dependencies from the lockfile
	npm ci

dev: ## The demo on http://localhost:5174 (mock API, no backend)
	npx vite --port 5174

seed: ## Rebuild the seed through the real backend in app/ (offline, no model)
	cd $(BACKEND) && uv run --quiet python ../../scripts/build_seed.py

# The seed is generated, and committed so the image build needs no Python. This
# proves the committed copy is what the builder makes today: a change to
# seed/world.py or app/ that was not followed by `make seed` fails here.
seed-check: seed ## Fail if the committed seed is not what the builder makes now
	git diff --exit-code --stat -- demo/static selfhost/example-documents
	test -z "$$(git status --porcelain -- demo/static selfhost/example-documents)"

lint: ## eslint --max-warnings 0, ruff on the seed builder, shellcheck
	npx eslint . --max-warnings 0
	uv run --quiet --project $(BACKEND) ruff check scripts seed
	shellcheck ci/*.sh scripts/*.sh

typecheck: ## tsc --noEmit — the mock is typed against the app's own contracts
	npx tsc --noEmit

test: ## vitest — the mock's contract with the app, and the replayed runs
	npx vitest run

build: ## vite build, then assert what it emitted
	npx vite build
	./ci/check-dist.sh

public: ## Fail if anything private or identifying is in the tree or its history
	python3 ci/check-privacy.py

verify: public lint typecheck test build ## The whole demo gate, in CI's order

# The real app, as copied: its own lint and tests, so a snapshot that does not
# pass them is never published as "the code you can run".
app-test: ## The snapshot's own gate: ruff, pytest, eslint, tsc, vitest in app/
	cd $(BACKEND) && uv run --quiet ruff check src tests && uv run --quiet pytest -q
	cd app/frontend && npm ci --silent && npm run lint && npm run typecheck && npm test

# `verify` checks the SOURCE. This checks what gets deployed: the image.
smoke: ## Build the image and prove it serves (needs docker only)
	./ci/smoke.sh

sync: ## Refresh app/ from the private repo: make sync SOURCE=<path> REF=<tag>
	./scripts/sync-from-tinternship.sh $(SOURCE) $(or $(REF),v1)
