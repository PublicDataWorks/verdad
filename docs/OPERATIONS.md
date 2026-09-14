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

- Deploys are manual; there is no deploy workflow in `.github/`. `.github/workflows/ci.yml` only runs lint + tests.
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
For local, non-Prefect runs use `scripts/run_stage.py` (see `AGENTS.md`); it uses whatever `.env` points at.

## Logs and monitoring

- Machine stdout/stderr: `fly logs -a processing-worker` (add `--machine <id>` for one process group; ids from
  `fly status -a <app>`). Same for `recording-worker`, `generic-recording-worker`, `prefect` (cron output lives here).
- Prefect UI: `https://prefect.fly.dev` (the `prefect` app exposes port 4200 over HTTPS). Flows use `log_prints=True`,
  so every `print()` in `src/` appears in the flow run logs. Whether the UI is behind any auth: **unknown**
  (nothing in the repo configures it).
- Sentry: `sentry_sdk.init(dsn=SENTRY_DSN)` in the three entrypoints. Project/org: **unknown**.
- Data-level health: row `status` columns (`New`, `Processing`, `Processed`, `Error`, `Ready for review`, `Reviewing`)
  on `audio_files`, `stage_1_llm_responses`, `snippets`; `error_message` holds the exception text.
