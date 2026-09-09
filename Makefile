# Makefile for easy development workflows.
# See development.md for docs.
# Note GitHub Actions call uv directly, not this Makefile.

.DEFAULT_GOAL := default

.PHONY: default install lint test test-backend docs-serve docs-build docs-check upgrade build trust-report action-icons clean

DOCS_ADDR ?= localhost:8000

default: install lint test

install:
	uv sync --locked --all-extras --dev

# Work on ClickNick and pyrung together without changing release dependencies.
# Set UV_NO_SYNC=1 for subsequent make lint/test and app runs in this environment.
.PHONY: install-pyrung-dev
install-pyrung-dev:
	uv pip install --editable ../pyclickplc --editable ../pyrung

lint:
	uv run python devtools/lint.py

test:
	uv run pytest --quiet --tb=short

# Cross-backend oracle: Access ODBC vs the Jet worker on the same MDB. Not run in CI.
test-backend:
	uv run pytest --quiet --tb=short -m backend tests/test_backend_oracle.py

docs-serve:
	uv run --group docs zensical serve --dev-addr $(DOCS_ADDR)

docs-build:
	uv run --group docs zensical build --clean --strict
	uv run --group docs python .github/scripts/check_public_site.py site

docs-check: docs-build

upgrade:
	uv lock --upgrade
	uv sync --locked --all-extras --dev

build:
	uv build

# Release trust report: SBOM + dependency table + release checks (dist/trust/).
# Needs network for uv audit; add TRUST_ARGS=--skip-audit when offline.
trust-report: build
	uv run python devtools/trust_report.py $(TRUST_ARGS)

action-icons:
	powershell -NoProfile -ExecutionPolicy Bypass -File devtools/generate_action_icons.ps1

# Improved Windows detection
ifeq ($(OS),Windows_NT)
    WINDOWS := 1
else
    ifeq ($(shell uname -s),Windows)
        WINDOWS := 1
    else
        WINDOWS := 0
    endif
endif

ifeq ($(WINDOWS),1)
	# Windows commands
	RM = powershell -Command "Remove-Item -Recurse -Force"
	FIND_PYCACHE = powershell -Command "Get-ChildItem -Path . -Filter '__pycache__' -Recurse -Directory | Remove-Item -Recurse -Force"
else
    # Unix commands
    RM = rm -rf
    FIND_PYCACHE = find . -type d -name "__pycache__" -exec rm -rf {} +
endif

clean:
	$(RM) dist/
	$(RM) *.egg-info/
	$(RM) .pytest_cache/
	$(RM) .mypy_cache/
	$(RM) .venv/
	$(FIND_PYCACHE)
