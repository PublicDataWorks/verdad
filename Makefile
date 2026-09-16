# Developer entry points. Run inside the project venv (`source .venv/bin/activate`).
RUFF ?= ruff
PYTEST ?= pytest

.PHONY: check test lint format

check: lint test  ## ruff + pytest (what CI runs)

test:  ## full test suite with coverage gate (see [tool.coverage.report] fail_under)
	$(PYTEST)

lint:  ## static checks only
	$(RUFF) check src tests scripts

format:  ## rewrite files in place (only run on files you are already changing)
	$(RUFF) format src tests scripts
