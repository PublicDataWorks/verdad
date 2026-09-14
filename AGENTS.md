# VERDAD backend: guide for coding agents

VERDAD records Spanish- and Arabic-language US radio stations around the clock and runs the audio through a
five-stage pipeline (Gemini 2.5 + OpenAI embeddings) that flags, clips, analyzes, reviews and embeds suspected
mis/disinformation. Results land in Supabase (Postgres + pgvector) and are reviewed by journalists in
[verdad-frontend](https://github.com/publicDataWorks/verdad-frontend). Orchestration is Prefect 3 on Fly.io.

## Layout (what is not obvious from file names)

- Path-specific guidance lives in `.claude/rules/` (pipeline stages, recorders, Supabase SQL, prompts,
  tests); each file loads only when you read files it matches.
- `src/processing_pipeline/stage_{1..5}/{flows,tasks,executors,models}.py`: one package per stage.
  `flows.py` = Prefect flow (loop that fetches work from Supabase), `tasks.py` = steps, `executors.py` =
  the LLM call. Stage 4 is `executor.py` + `agents.py` (Google ADK agent pipeline) and stage 2 has no executor.
- `src/processing_pipeline/main.py`: production entrypoint. Reads `FLY_PROCESS_GROUP` and `serve()`s the matching
  Prefect deployment (`fly.processing_worker.toml` `[processes]` lists the 11 valid values). With no value it raises.
- `src/recording.py` (ffmpeg stream recorders) and `src/generic_recording.py` + `src/radiostations/` (Selenium/Chrome
  recorders for six web-only stations). Same `FLY_PROCESS_GROUP` dispatch.
- `config/stations.yaml` + `src/stations.py`: the station list and its loader/validator (`load_stations`,
  `stations_for`, `station_dicts`, and `python -m stations prefect-runs` for `scripts/start_recording.sh`).
- `src/utils.py`: `optional_flow`/`optional_task` decorators and `fetch_radio_stations()` (see gotchas).
- `src/processing_pipeline/supabase_utils.py`: the only DB access layer (`SupabaseClient`).
- `prompts/`: prompt sources, but the pipeline reads prompts from the `prompt_versions` table.
- `supabase/`: 5 migrations plus loose SQL in `supabase/database/sql/` (not migrations). `server/`: separate
  Express/TS app (Liveblocks auth, Resend email) with its own Dockerfile and `fly.server.toml`.
- `scripts/*.sh` + `Dockerfile.*` + `fly.*.toml`: deploy and cron. See `docs/OPERATIONS.md`.
- `docs/design-2024.md`: historical design doc (two-stage era). Do not treat it as current.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt   # needs ffmpeg on PATH
make check          # ruff check + pytest with coverage gate; what CI runs. Run before every commit.
make lint           # ruff check src tests scripts + scripts/check_rules.py
make test           # pytest (coverage gate = [tool.coverage.report] fail_under in pyproject.toml)
pytest tests/processing_pipeline/test_stage_3.py -k executor --no-cov     # one file/test, fast
make format         # ruff format; only run on files you are already changing (repo is not yet fully formatted)
python scripts/run_stage.py --stage 3 --snippet-id <uuid>                  # run one stage locally, no Prefect
PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import --version 1.2.0 --description "..." [--dry-run]
```

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

- Stations live in `config/stations.yaml`, loaded and validated by `src/stations.py`; adding or disabling one is
  a single YAML entry plus a deploy (docs/OPERATIONS.md, "Adding or disabling a station").
- Each station's `recorder` field (`max` | `lite` | `generic`) is what assigns it to a recorder -- there is no
  positional split any more. It is a topology fact tied to the `fly.*.toml` process groups, so it only takes
  effect on deploy. See `.claude/rules/recorders.md` first.
- `src/main.py` is an ad-hoc stage 4 smoke script with a hard-coded production snippet UUID. Do not run it.
- `ENABLE_PREFECT_DECORATOR=false` (set by tests and `scripts/run_stage.py`) makes flows/tasks plain functions.
  It is read at import time, so set it before importing anything from `src/`.
- Prompts live in the DB. Editing `prompts/*.md` changes nothing until `import_prompts_to_db.py` runs.
- The coverage gate (`fail_under`) is set to the real number and is meant to ratchet upward; do not lower it.
- Import sorting (`ruff` rule `I`) is intentionally off until a formatting-only commit lands; do not reformat
  files you are not otherwise changing.

## Rules

- Run `make check` before committing. Fix what you broke; do not skip, delete or weaken a failing test to go green.
  If a test exposes a real bug, leave the test failing, mark it `xfail(strict=True)` with the reason, and report it.
- Never deploy (`fly deploy`, `fly machine ...`, `fly secrets set`), run migrations, import prompts, or write to
  production data unless explicitly asked. `scripts/run_stage.py` and `src/scripts/*` hit whatever `.env` points at.
- Do not commit `.env`, credentials, or the Supabase project URL/keys anywhere new.
- Keep commits focused; separate mechanical formatting from behavior changes.
