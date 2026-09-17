# Operations

Everything below is read from the repo (`fly.*.toml`, `Dockerfile.*`, `scripts/`, `src/processing_pipeline/main.py`).
Items marked **unknown** are not recorded anywhere in the repo; ask a maintainer before relying on them.

## Fly apps

| Fly app (config) | Dockerfile | Entrypoint | Process groups (`FLY_PROCESS_GROUP`) |
|---|---|---|---|
| `prefect` (`fly.prefect.toml`) | `Dockerfile.prefect` (prefecthq/prefect:3.4.24-python3.11 + supercronic + flyctl) | `server`: `scripts/start_prefect_server.sh` (port 4200, health `/api/health`); `cron`: `scripts/start_cron.sh` | `server`, `cron` |
| `processing-worker` (`fly.processing_worker.toml`) | `Dockerfile.processing_worker` (python3.12 + node22 + ffmpeg + `@google/gemini-cli@0.20.0`) | `scripts/trigger_processing_worker.sh` -> waits for `https://prefect.fly.dev/api/health` -> `python src/processing_pipeline/main.py` | `initial_disinformation_detection`, `initial_disinformation_detection_2`, `audio_clipping`, `in_depth_analysis`, `regenerate_timestamped_transcript`, `redo_main_detection`, `undo_disinformation_detection`, `undo_audio_clipping`, `analysis_review`, `analysis_review_2`, `embedding` |
| `recording-worker` (`fly.recording_worker.toml`) | `Dockerfile.recording_worker` (python:3.12-slim + ffmpeg) | `scripts/recording.sh` -> `python src/recording.py` | `max_recorder` (stations `[:39]`, 8 GB), `lite_recorder` (stations `[39:]`, 4 GB) |
| `generic-recording-worker` (`fly.generic_recording_worker.toml`) | `Dockerfile.generic_recording_worker` (ubuntu + Chrome + pulseaudio) | `scripts/generic_recording.sh` -> `python src/generic_recording.py` | `radio_khot`, `radio_kisf`, `radio_krgt`, `radio_wkaq`, `radio_wado`, `radio_waqi` (one machine each) |
| `verdad-searxng` (`fly.searxng.toml`) | `Dockerfile.searxng` (searxng/searxng:2025.12.26 + `searxng/config/settings.yml`) | image default | none; serves `https://verdad-searxng.fly.dev` used via `SEARXNG_URL` (stage 3 tools, stage 4 MCP) |
| `verdad-dev` (`fly.dev.toml`) | `Dockerfile.generic_recording_worker` | same as generic recorder | none defined. Purpose **unknown** (looks like a scratch app) |
| `verdad-server` (`server/fly.server.toml`) | `server/Dockerfile.server` | Express/TS app on port 3000 (Liveblocks auth, Resend email) | `app` |

Each process group is one Fly machine. `src/processing_pipeline/main.py` maps the group name to a Prefect flow and
calls `serve(flow.to_deployment(name=...))`, so the deployments exist only while the worker machine is running.
`initial_disinformation_detection_2` and `analysis_review_2` are second copies of the stage 1 / stage 4 workers.

## Deploying

```bash
fly deploy -c fly.processing_worker.toml      # from the repo root; same for the other root fly.*.toml files
cd server && fly deploy -c fly.server.toml    # the server app builds from server/
```

- App deploys are manual; no workflow in `.github/` runs `fly deploy`. `.github/workflows/ci.yml` runs lint + tests.
  Prompt changes are the exception: `prompts-check.yml` (PR: unit tests + manifest bump check),
  `prompt-evaluation.yml` (PR: runs `src/scripts/evaluate_prompt.py` and posts a report comment) and
  `prompts-deploy.yml` (push to `main`: `import_prompts_to_db.py import --from-manifest`). The last two start a
  one-off Machine in the `processing-worker` app via `scripts/ci/fly_prompt_job.sh`, authenticated with the
  `FLY_API_TOKEN` repository secret; see `docs/PROMPT_EVALUATION.md`.
- Secrets (`SUPABASE_*`, `R2_*`, `GOOGLE_GEMINI_KEY`, `OPENAI_API_KEY`, `SEARXNG_URL`, `SENTRY_DSN`, ...) are Fly
  secrets per app (`fly secrets list -a <app>`); their values are not in the repo. `PREFECT_API_URL` is set in each
  `fly.*.toml` `[env]` (and hard-coded as `https://prefect.fly.dev/api` in `scripts/*.sh` and `Dockerfile.prefect`).
- Who has deploy rights and the Fly org/billing owner: **unknown** (org name `verdad` per CLAUDE.md).

## The 6-hourly restart cycle (`prefect` app, `cron` process)

`scripts/start_cron.sh` writes this crontab and runs it with supercronic:

```
0 */6 * * * /app/restart_all.sh            # every 6 hours
0 1 * * *   python3 /app/delete_flow_runs.py   # daily 01:00 UTC
```

`scripts/restart_all.sh` does, in order:

1. `src/scripts/cancel_all_flows.py`: sets every RUNNING/PENDING flow run to Cancelling via the Prefect API.
2. `fly machine restart <id>` for each id in `$FLY_MACHINE_IDS` (comma-separated Fly secret on the `prefect` app;
   values **unknown**). Needs flyctl auth on that machine (`FLY_API_TOKEN`, **unknown** how it is provided).
3. Waits 30 s, runs `start_recording.sh` (one `prefect deployment run` per station, 59 stations), waits 10 s,
   runs `start_processing.sh` (N runs per stage: `STAGE_{1..5}_FLOW_RUNS`, defaults 2/1/2/1/1).

`delete_flow_runs.py` deletes old cancelled flow runs in batches (`BATCH_SIZE`, `DELAY_BETWEEN_BATCHES`).

Why the full restart exists is **not documented** in the repo. Observable facts: every flow loops forever
(`repeat=True`, or `limit` for stage 1) and sleeps 60 s when idle; the stage workers `serve(..., limit=100)`; the restart is the only thing that
re-creates flow runs after a worker machine dies. Treat it as load-bearing until someone confirms otherwise.

## Triggering one stage run against production

Deployment names are `"<flow name>/<deployment name>"` (from `main.py`; note stage 3 differs in case):

```bash
export PREFECT_API_URL=https://prefect.fly.dev/api
prefect deployment run "Stage 1: Initial Disinformation Detection/Stage 1: Initial Disinformation Detection" \
    --params '{"audio_file_id": "<uuid>", "limit": 1}'
prefect deployment run "Stage 3: In-depth Analysis/Stage 3: In-Depth Analysis" \
    --params '{"snippet_ids": ["<uuid>"], "skip_review": false, "repeat": false}'
prefect deployment run "Stage 4: Analysis Review/Stage 4: Analysis Review" \
    --params '{"snippet_ids": ["<uuid>"], "repeat": false}'
prefect deployment run "Stage 1: Undo Disinformation Detection/Stage 1: Undo Disinformation Detection" \
    --params '{"audio_file_ids": ["<uuid>"]}'
```

The matching worker machine must be up for the run to be picked up (`fly status -a processing-worker`).
For local, non-Prefect runs use `scripts/run_stage.py` (see `AGENTS.md`); it uses whatever `.env` points at and
refuses the production project unless `--allow-production` is passed.

## Gotchas learned in production (September 2026)

- **Workers idle after any deploy or `prefect` app restart.** Flow runs are created only by the 6-hourly cron
  (00:10/06:10/12:10/18:10 UTC); a freshly deployed `serve()` has nothing to serve until then. Either wait for the
  tick or create the runs yourself:

  ```bash
  API=https://prefect.fly.dev/api
  ID=$(curl -sS "$API/deployments/name/Stage%203%3A%20In-depth%20Analysis/Stage%203%3A%20In-Depth%20Analysis" | jq -r .id)
  curl -sS -X POST "$API/deployments/$ID/create_flow_run" -H 'content-type: application/json' \
      -d '{"parameters": {"repeat": true, "skip_review": false, "snippet_ids": []}}'
  ```

  Per tick the cron creates `STAGE_{1..5}_FLOW_RUNS` runs per stage (Fly secrets on the `prefect` app; production
  currently 4/1/5/1/1). Dead runs stay `Running` in the UI until the next tick cancels them; harmless.
- **`fly secrets set ... -a prefect` (or any `prefect` restart) crashes every running flow run within ~2 min**
  ("Concurrency lease renewal failed"). Do it when nothing targeted is in flight, then recreate the runs as above.
- **OOM leaves zombie runs.** When a worker machine is OOM-killed (`exit_code=137` in `fly machine status`) the
  process restarts but its Prefect runs never resume and keep showing `Running`. Check `fly logs`, not Prefect
  state. The stage 3 machine runs 4 GB for this reason (5 loop runs plus targeted by-id runs).
- **Every restart strands in-flight rows** in `Processing`/`Reviewing`; nothing resets them. The stage 3
  `on_crashed` hook resets only rows named in `snippet_ids`.
- **Stage 3 polls `New` newest-first**, so old rows never drain on their own; reprocess them by id.
- **`analyze_snippet` has no retry**: one Gemini 503/429 sends the snippet to `Error` with the message stored.
  Expect a few percent per batch; rerun those ids once.
- **Gemini quota**: about 2,800 stage 3 analyses per day at the current tier, reset 07:00 UTC (midnight PT).
  5 loop runs already use most of it; `429 RESOURCE_EXHAUSTED` errors need a requeue after the reset.
- **PostgREST statement timeout is 2 min**: big counts/updates time out through the API; use the Supabase SQL
  editor (or `psql`). Targeted reprocessing of many ids: `src/scripts/reprocess_snippets.py`.
- **Run `src/scripts/*` against production from a one-off machine** with the current image
  (`fly machines list -a processing-worker --json | jq -r '.[0].config.image'`) and inherited secrets:

  ```bash
  fly machine run <image> -a processing-worker -r sjc --detach --restart no \
      --vm-memory 1024 --metadata prompt_job=<tag> --entrypoint bash -- -c "cd /app && python src/scripts/<script>.py"
  fly logs -m <machine id> --no-tail; fly machine destroy <machine id> --force
  ```
- The Prefect API and UI (`https://prefect.fly.dev`) have no authentication.

## Database schema and migrations

`supabase/migrations/` is the only place schema changes belong. It holds the baseline, one comment-only placeholder
per version production has already applied (29), and `applied_versions.txt`.

- **`20260915000000_baseline_public_schema.sql`** is a generated snapshot of the live `public` and `profiles`
  schemas (33 tables, 1 materialized view, 3 enums, 54 functions, 22 triggers, 59 non-constraint indexes, RLS
  on 29 tables, 16 policies, grants and comments; regenerated 2026-09-17 before it was marked applied). It was produced by `scripts/dump_schema_baseline.py`, which
  only runs `SELECT`s against the catalog through the Supabase Management API. **It has never been executed
  against production** - production already has every object in it, and the file refuses to run where
  `public.snippets` exists. It is the only file up to its version with SQL in it, so a fresh database
  (`supabase start`, `supabase db reset`) is built from it alone, and it is the reference for what runs in
  production.
- The 29 comment-only files are placeholders for the versions in `supabase_migrations.schema_migrations`: 24 whose
  SQL never landed in git, plus the 2024 `remote_schema` dump and the four bare-date `20260129_*` files (renamed to
  the 14-digit versions the database recorded) whose bodies the baseline supersedes; git history keeps them. They
  exist so `supabase migration list` lines up, and `tests/test_migrations.py` asserts they stay comment-only.
- `applied_versions.txt` is `supabase_migrations.schema_migrations` as of the date in its header; the tests check
  that files and manifest agree. `make migrations-manifest` refreshes it and `make baseline-check` regenerates the
  baseline and diffs it against the committed file (both need `SUPABASE_ACCESS_TOKEN`).
- What the baseline does not carry: object ownership, `ALTER DEFAULT PRIVILEGES`, `REVOKE`s, column-level grants,
  and grants to roles other than `anon`, `authenticated` and `service_role`. On a rebuilt database the 31
  `SECURITY DEFINER` functions therefore run as whoever applied the migration, not necessarily production's owner.
- `supabase/database/sql/` is historical hand-applied SQL, not migrations - see the README in that directory.

### Rules for new migrations

- One file per change in `supabase/migrations/`, named `YYYYMMDDHHMMSS_short_name.sql` with a **full 14-digit
  timestamp**. Never a bare date: `supabase` parses the leading digits as the version, so `20260914_a.sql` and
  `20260914_b.sql` are both version `20260914` and `supabase db push` fails on the `schema_migrations` primary
  key after the first one. Two open PRs (#73, #76) collide this way today.
- Date the file after the baseline (`20260915000000`), so it sorts after it.
- If you apply SQL by hand (SQL editor, dashboard, MCP), still commit the file, and then tell the database it
  is done: `supabase migration repair --linked --status applied <version>`. Skipping that is how the repo ended
  up with 28 remote-only versions.
- `CREATE INDEX CONCURRENTLY` cannot run inside a transaction, so it cannot run under `supabase db push`. Keep
  such statements in their own file, apply them by hand, and `migration repair --status applied` afterwards.
- Never edit a migration that has been applied; write a new one.

### Human steps after a migration PR merges

Needs `SUPABASE_ACCESS_TOKEN` and the database password.

```bash
supabase link --project-ref dzujjhzgzguciwryzwlx
supabase migration list --linked                    # expect: 29 versions local = remote, baseline local-only
supabase migration repair --linked --status applied 20260915000000
supabase migration list --linked                    # expect: everything aligned, nothing local-only
supabase db diff --linked --schema public,profiles   # expect: no schema changes found (needs Docker)
```

Without Docker, `db diff` cannot build its shadow database; dump and compare instead:

```bash
supabase db dump --linked --schema public,profiles -f /tmp/live.sql
# then diff /tmp/live.sql against the baseline by object (ordering and formatting differ):
grep -E '^(CREATE|ALTER) ' /tmp/live.sql | sort > /tmp/live.objects
grep -E '^(CREATE|ALTER) ' supabase/migrations/20260915000000_baseline_public_schema.sql | sort > /tmp/base.objects
diff /tmp/live.objects /tmp/base.objects
```

If PR #73 or #76 was applied by hand in the meantime, `migration repair --linked --status applied` their
(renamed, 14-digit) versions too.

## Logs and monitoring

- Machine stdout/stderr: `fly logs -a processing-worker` (add `--machine <id>` for one process group; ids from
  `fly status -a <app>`). Same for `recording-worker`, `generic-recording-worker`, `prefect` (cron output lives here).
- Prefect UI: `https://prefect.fly.dev` (the `prefect` app exposes port 4200 over HTTPS). Flows use `log_prints=True`,
  so every `print()` in `src/` appears in the flow run logs. The UI and API have no authentication.
- Sentry: `sentry_sdk.init(dsn=SENTRY_DSN)` in the three entrypoints. Project/org: **unknown**.
- Data-level health: row `status` columns (`New`, `Processing`, `Processed`, `Error`, `Ready for review`, `Reviewing`)
  on `audio_files`, `stage_1_llm_responses`, `snippets`; `error_message` holds the exception text.
