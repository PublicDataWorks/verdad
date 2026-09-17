# Developer entry points. Run inside the project venv (`source .venv/bin/activate`).
RUFF ?= ruff
PYTEST ?= pytest

.PHONY: check test lint format migrations-manifest baseline-check

check: lint test  ## ruff + pytest (what CI runs)

test:  ## full test suite with coverage gate (see [tool.coverage.report] fail_under)
	$(PYTEST)

lint:  ## static checks only
	$(RUFF) check src tests scripts
	python scripts/check_rules.py

format:  ## rewrite files in place (only run on files you are already changing)
	$(RUFF) format src tests scripts

migrations-manifest:  ## refresh supabase/migrations/applied_versions.txt from production (needs SUPABASE_ACCESS_TOKEN)
	python scripts/dump_schema_baseline.py --applied-versions -o supabase/migrations/applied_versions.txt

baseline-check:  ## regenerate the baseline from production and diff it against the committed file (needs SUPABASE_ACCESS_TOKEN)
	python scripts/dump_schema_baseline.py -o /tmp/baseline_check.sql
	diff -u supabase/migrations/20260915000000_baseline_public_schema.sql /tmp/baseline_check.sql
