.PHONY: init sync format lint typecheck test check run tree clean

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

tree: ## Show top of repo tree
	find . -maxdepth 3 \( -path ./.git -o -path ./.venv -o -path ./.ruff_cache -o -path ./.mypy_cache -o -path ./.pytest_cache -o -path ./node_modules \) -prune -o -print | sort

clean: ## Remove caches
	rm -rf .ruff_cache .mypy_cache .pytest_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
