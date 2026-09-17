---
paths:
  - "tests/**"
---

# Tests

## What conftest already does

`tests/conftest.py` inserts `<repo>/src` on `sys.path` (so pipeline imports are `from processing_pipeline...`;
only the `src/scripts/*` tests import `from src.scripts ...`, because those scripts import
`src.processing_pipeline.*` themselves and `pythonpath = ["."]` in `pyproject.toml` puts the repo root on the
path) and sets dummy `GOOGLE_GEMINI_KEY`, `GOOGLE_GEMINI_PAID_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`,
`R2_*` and `SENTRY_DSN` **before** any test imports. It also sets `ENABLE_PREFECT_DECORATOR=false`, which
`optional_flow`/`optional_task` read at import time, so flows and tasks are plain functions in tests - call
them directly, do not expect Prefect behavior, and do not import anything from `src/` before conftest runs.

`OPENAI_API_KEY` is deliberately not set; a test that needs it sets it itself. A `test_data_dir` fixture
gives a scratch directory that is emptied and removed afterwards.

## No network, ever

Nothing in the suite may call Gemini, OpenAI, R2, Supabase or download chromedriver. Patch names where the
module under test bound them (`processing_pipeline.stage_1.flows.SupabaseClient`, `...flows.genai`,
`radiostations.base.ChromeDriverManager`, `recording.s3_client`), not the upstream package. Patch the loop
sleeps too (`time.sleep`, `...flows.asyncio.sleep`) so `repeat=True` tests do not idle for 60s.

Stage 2 tests decode real mp3 fixtures with pydub, so `ffmpeg` must be on `PATH` (CI and the web
SessionStart hook install it). If stage 2 tests fail with a pydub/ffmpeg error, that is the cause.

## Running

```bash
make test                                                          # full suite, coverage gate
make check                                                         # ruff + tests; run before committing
pytest tests/processing_pipeline/test_stage_3.py -k executor --no-cov   # one file/test; --no-cov skips the gate
```

Without `--no-cov`, a subset run fails on coverage even when every test passes - always add it for targeted
runs, never to the full run.

## Coverage gate and failing tests

`fail_under` in `[tool.coverage.report]` (`pyproject.toml`) is the real current number and ratchets **up**
only. Do not lower it, and do not add `# pragma: no cover` to get under it.

Never weaken, skip or delete a test to go green. If a test exposes a real bug you are not fixing, leave it
failing, mark it `@pytest.mark.xfail(strict=True, reason="...")` with a concrete reason, and report it -
`strict=True` means it fails the suite again the moment the bug is fixed.
