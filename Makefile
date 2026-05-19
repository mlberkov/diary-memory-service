.PHONY: init sync format lint typecheck test check run tree clean backup-up backup-run backup-prune restore-plan restore-run

# Use uv as the canonical entrypoint (D-017). uv resolves a Python 3.11
# interpreter from .python-version and manages the lockfile.

UV ?= uv

init: ## Print toolchain versions
	$(UV) --version
	$(UV) run python --version

sync: ## Install/refresh dependencies into the uv-managed venv
	$(UV) sync --all-extras

format: ## Apply Ruff formatting and lint autofixes
	$(UV) run ruff format src tests
	$(UV) run ruff check --fix src tests

lint: ## Ruff lint + format check (no writes)
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

typecheck: ## Mypy strict typecheck
	$(UV) run mypy

test: ## Pytest
	$(UV) run pytest

check: lint typecheck test ## Full pre-merge gate

run: ## Boot the FastAPI app on 127.0.0.1:8000 (Slice 1.1 smoke)
	$(UV) run python -m memory_rag

backup-up: ## Start the opt-in nightly backup sidecar (OP-4.2 Compose profile "backup")
	docker compose --profile backup up -d

backup-run: ## Run one base backup now (one-off; shares the scheduler's lock)
	docker compose --profile backup run --rm --entrypoint sh pg_backup /opt/pg_backup/backup.sh

backup-prune: ## Run retention pruning now (one-off; shares the scheduler's lock)
	docker compose --profile backup run --rm --entrypoint sh pg_backup /opt/pg_backup/prune.sh

# OP-4.3 restore tooling. Pass restore.sh flags via RESTORE_ARGS, e.g.
#   make restore-plan RESTORE_ARGS="--backup-dir=/archive/base/base-<ts> --target=latest"
#   make restore-run  RESTORE_ARGS="--backup-dir=/archive/base/base-<ts> --target=latest --yes"
RESTORE_ARGS ?=

restore-plan: ## Dry-run a restore — validate the backup + WAL and print the plan, write nothing (set RESTORE_ARGS)
	docker compose --profile restore run --rm --entrypoint sh pg_restore /opt/pg_restore/restore.sh --dry-run $(RESTORE_ARGS)

restore-run: ## Prepare a recovered data dir from a base backup + WAL (RESTORE_ARGS must include --yes); then `docker compose --profile restore up -d pg_restore`
	docker compose --profile restore run --rm --entrypoint sh pg_restore /opt/pg_restore/restore.sh $(RESTORE_ARGS)

tree: ## Show top of repo tree
	find . -maxdepth 3 \( -path ./.git -o -path ./.venv -o -path ./.ruff_cache -o -path ./.mypy_cache -o -path ./.pytest_cache -o -path ./node_modules \) -prune -o -print | sort

clean: ## Remove caches
	rm -rf .ruff_cache .mypy_cache .pytest_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
