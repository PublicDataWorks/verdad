# VERDAD backend: guide for coding agents

VERDAD records Spanish- and Arabic-language US radio stations around the clock and runs the audio through a
five-stage pipeline (Gemini 2.5 + OpenAI embeddings) that flags, clips, analyzes, reviews and embeds suspected
mis/disinformation. Results land in Supabase (Postgres + pgvector) and are reviewed by journalists in
[verdad-frontend](https://github.com/publicDataWorks/verdad-frontend). Orchestration is Prefect 3 on Fly.io.

## Layout (what is not obvious from file names)

- `src/processing_pipeline/stage_{1..5}/{flows,tasks,executors,models}.py`: one package per stage.
  `flows.py` = Prefect flow (loop that fetches work from Supabase), `tasks.py` = steps, `executors.py` =
  the LLM call. Stage 4 is `executor.py` + `agents.py` (Google ADK agent pipeline) and stage 2 has no executor.
- `src/processing_pipeline/main.py`: production entrypoint. Reads `FLY_PROCESS_GROUP` and `serve()`s the matching
  Prefect deployment (`fly.processing_worker.toml` `[processes]` lists the 11 valid values). With no value it raises.
- `src/recording.py` (ffmpeg stream recorders) and `src/generic_recording.py` + `src/radiostations/` (Selenium/Chrome
  recorders for six web-only stations). Same `FLY_PROCESS_GROUP` dispatch.
- `src/utils.py`: `optional_flow`/`optional_task` decorators and `fetch_radio_stations()` (see gotchas).
- `src/processing_pipeline/supabase_utils.py`: the only DB access layer (`SupabaseClient`).
- `prompts/`: source of truth for LLM prompts, but the pipeline reads prompts from the `prompt_versions` table.
  `src/scripts/import_prompts_to_db.py` pushes files to the DB; the `.claude/skills/verdad-heuristics-updater`
  skill wraps that workflow for heuristics changes.
- `supabase/`: `migrations/` is the source of truth (generated baseline of the live schema + one file per
  applied version); `supabase/database/sql/` is historical hand-applied SQL, see its README and the
  "Database schema and migrations" section of `docs/OPERATIONS.md`. `server/`: separate
  Express/TS app (Liveblocks auth, Resend email) with its own Dockerfile and `fly.server.toml`.
- `scripts/*.sh` + `Dockerfile.*` + `fly.*.toml`: deploy and cron. See `docs/OPERATIONS.md`.
- `docs/design-2024.md`: historical design doc (two-stage era). Do not treat it as current.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt   # needs ffmpeg on PATH
make check          # ruff check + pytest with coverage gate; what CI runs. Run before every commit.
make lint           # ruff check src tests scripts
make test           # pytest (coverage gate = [tool.coverage.report] fail_under in pyproject.toml)
pytest tests/processing_pipeline/test_stage_3.py -k executor --no-cov     # one file/test, fast
make format         # ruff format; only run on files you are already changing (repo is not yet fully formatted)
python scripts/run_stage.py --stage 3 --snippet-id <uuid>                  # run one stage locally, no Prefect
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --version 1.2.0 --description "..." [--dry-run]
```

- Tests import from `src/` via `tests/conftest.py` (`sys.path`) and set dummy `SUPABASE_*`, `R2_*`, `GOOGLE_GEMINI_KEY`
  and `ENABLE_PREFECT_DECORATOR=false`. `OPENAI_API_KEY` is not set there; tests that need it set it themselves.
- Stage 2 tests decode real mp3s with pydub, so `ffmpeg` must be installed (CI and the web SessionStart hook do this).
- `pre-commit install` enables ruff on staged files; `hooks/install-hooks.sh` installs a lint+test pre-push hook.

## Environment variables

Complete list with one-line explanations: `.env.sample`. Everything is read with `os.getenv` at flow start; nothing
validates them up front, so a missing key surfaces as an error inside the flow. In production they are Fly secrets
(`fly secrets set -a <app>`); `PREFECT_API_URL` and `FLY_PROCESS_GROUP` come from the `fly.*.toml` files.

## How deploy works

- One Fly app per `fly.*.toml`, deployed manually: `fly deploy -c fly.processing_worker.toml` (there is no deploy CI).
  Each `[processes]` entry becomes a machine whose `FLY_PROCESS_GROUP` selects the Prefect deployment to serve.
- The `prefect` app runs the Prefect server plus a `cron` machine (supercronic): `scripts/restart_all.sh` every 6 hours
  cancels all flow runs, `fly machine restart`s `$FLY_MACHINE_IDS`, then re-triggers `start_recording.sh` and
  `start_processing.sh`; `src/scripts/delete_flow_runs.py` runs daily. The rationale for the 6-hourly restart is
  undocumented in the repo.
- Details, deployment names and how to trigger a single stage run: `docs/OPERATIONS.md`.

## Gotchas

- Stations are hard-coded: 53 dicts in `src/utils.py::fetch_radio_stations()`, split by position in
  `src/recording.py` (`radio_stations[:39]` -> max recorder, `[39:]` -> lite recorder), and duplicated by name in
  `scripts/start_recording.sh`. Adding or reordering a station touches all three and shifts the split.
- `src/main.py` is an ad-hoc stage 4 smoke script with a hard-coded production snippet UUID. Do not run it.
- `ENABLE_PREFECT_DECORATOR=false` (set by tests and `scripts/run_stage.py`) makes flows/tasks plain functions.
  It is read at import time, so set it before importing anything from `src/`.
- Prompts live in the DB. Editing `prompts/*.md` changes nothing until `import_prompts_to_db.py` runs.
- The coverage gate (`fail_under`) is set to the real number and is meant to ratchet upward; do not lower it.
- Stage flows loop with `repeat=True` (stage 1: `limit`, set to 1000/10000 in production) and sleep 60s when idle; pass `repeat=False`
  (or a specific id) when calling them yourself.
- Snippets with overall confidence >= 95 (`CONFIDENCE_THRESHOLD`) go to stage 4 review; the rest are `Processed`.
- Import sorting (`ruff` rule `I`) is intentionally off until a formatting-only commit lands; do not reformat
  files you are not otherwise changing.

## Rules

- Run `make check` before committing. Fix what you broke; do not skip, delete or weaken a failing test to go green.
  If a test exposes a real bug, leave the test failing, mark it `xfail(strict=True)` with the reason, and report it.
- Never deploy (`fly deploy`, `fly machine ...`, `fly secrets set`), run migrations, import prompts, or write to
  production data unless explicitly asked. `scripts/run_stage.py` and `src/scripts/*` hit whatever `.env` points at.
- Do not commit `.env`, credentials, or the Supabase project URL/keys anywhere new.
- Keep commits focused; separate mechanical formatting from behavior changes.
