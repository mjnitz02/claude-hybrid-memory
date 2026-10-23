# Day-to-day commands for this repo. `make` alone lists them.
#
# Tools run through uv, so their versions come from uv.lock, and the pre-commit hooks,
# CI and this file all run the same ruff and pytest.

MEM_BIN := $(shell uv tool dir --bin 2>/dev/null || echo $(HOME)/.local/bin)/mem

.DEFAULT_GOAL := help
.PHONY: help sync lint fix test test-live check pre-commit hooks install install-check

help: ## List the targets
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install the dev environment from uv.lock
	uv sync --locked

lint: ## ruff check, no changes
	uv run ruff check .

fix: ## ruff check, applying safe fixes
	uv run ruff check --fix .

test: ## Unit tests (synthetic fixture stores only)
	uv run pytest

test-live: ## Read-only tests against this machine's real store and installed `mem`
	uv run pytest -m live

check: pre-commit test ## What CI runs

pre-commit: ## Every pre-commit hook over every file
	uv run pre-commit run --all-files

hooks: ## Install the git hooks: lint + secret scan on commit, tests on push
	uv run pre-commit install

install: ## Install `mem`, then set up or repair the store, skills and Claude Code hooks
	uv tool install -e . --reinstall
	$(MEM_BIN) install --repo $(CURDIR) --mem $(MEM_BIN)

install-check: ## What `make install` would change, writing nothing
	$(MEM_BIN) install --dry-run --repo $(CURDIR) --mem $(MEM_BIN)
