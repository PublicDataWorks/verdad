# Operations

Everything below is read from the repo (`fly.*.toml`, `Dockerfile.*`, `scripts/`, `src/processing_pipeline/main.py`).
Items marked **unknown** are not recorded anywhere in the repo; ask a maintainer before relying on them.

## Fly apps

| Fly app (config) | Dockerfile | Entrypoint | Process groups (`FLY_PROCESS_GROUP`) |
|---|---|---|---|
| `prefect` (`fly.prefect.toml`) | `Dockerfile.prefect` (prefecthq/prefect:3.4.24-python3.11 + supercronic + flyctl) | `server`: `scripts/start_prefect_server.sh` (port 4200, health `/api/health`); `cron`: `scripts/start_cron.sh` | `server`, `cron` |
| `processing-worker` (`fly.processing_worker.toml`) | `Dockerfile.processing_worker` (python3.12 + node22 + ffmpeg + `@google/gemini-cli@0.20.0`) | `scripts/trigger_processing_worker.sh` -> waits for `https://prefect.fly.dev/api/health` -> `python src/processing_pipeline/main.py` | `initial_disinformation_detection`, `initial_disinformation_detection_2`, `audio_clipping`, `in_depth_analysis`, `regenerate_timestamped_transcript`, `redo_main_detection`, `undo_disinformation_detection`, `undo_audio_clipping`, `analysis_review`, `analysis_review_2`, `embedding` |
| `recording-worker` (`fly.recording_worker.toml`) | `Dockerfile.recording_worker` (python:3.12-slim + ffmpeg) | `scripts/recording.sh` -> `python src/recording.py` | `max_recorder` (`recorder: max` stations, currently 39, 8 GB), `lite_recorder` (`recorder: lite`, currently 14, 4 GB) |
| `generic-recording-worker` (`fly.generic_recording_worker.toml`) | `Dockerfile.generic_recording_worker` (ubuntu + Chrome + pulseaudio) | `scripts/generic_recording.sh` -> `python src/generic_recording.py` | `radio_khot`, `radio_kisf`, `radio_krgt`, `radio_wkaq`, `radio_wado`, `radio_waqi` (one machine each; the `process_group` of each `recorder: generic` station in `config/stations.yaml`) |
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

## Adding or disabling a station

The station list is `config/stations.yaml` (loaded and validated by `src/stations.py`). Nothing else holds
station data: both recorders, `scripts/start_recording.sh` and the generic recorder all read that file.

1. **Edit `config/stations.yaml`.** Add an entry with `code`, `name`, `url`, `state` and `recorder`
   (`max` | `lite` | `generic`), or set `enabled: false` on an existing one to stop recording it. `code` and
   `url` must be unique. Check your edit locally:

   ```bash
   PYTHONPATH=src python -m stations codes --recorder max     # what the max machine will serve
   PYTHONPATH=src python -m stations prefect-runs             # what start_recording.sh will trigger
   make check
   ```

   `code` is the Prefect deployment name and `url` determines the R2 prefix
   (`radio_<last 6 hex of sha256(url)>/`): renaming a code orphans its deployment, and changing a url moves
   where that station's audio lands.

2. **Check memory sizing** if you added a `recorder: max` station. `max_recorder` runs one ffmpeg process per
   station on a single 8 GB / 8 shared-CPU machine (`lite_recorder` is 4 GB); bump `[[vm]] memory` in
   `fly.recording_worker.toml` in the same PR if the count grows meaningfully. Prefer `lite` when unsure.

3. **A `recorder: generic` station needs more.** It also needs `process_group: radio_<slug>`, a `driver` block
   (unique PulseAudio `sink`/`source`, plus the play-button and video-element CSS selectors of its web player),
   a matching `[processes]` entry and `[[vm]]`/`[scale]` sizing in `fly.generic_recording_worker.toml`, and one
   Fly machine of its own (Chrome + PulseAudio, ~1 GB each).

4. **Deploy.** Both apps that read the file:

   ```bash
   fly deploy -c fly.recording_worker.toml          # the recorders themselves
   fly deploy -c fly.prefect.toml                   # the cron image copies config/stations.yaml + src/stations.py
   fly deploy -c fly.generic_recording_worker.toml  # only for a generic station
   ```

   Deployments exist only while the worker machine runs, so the new station starts recording after the
   recording worker restarts and the next `start_recording.sh` triggers its run (at most 6 hours; run
   `/app/start_recording.sh` on the `cron` machine to do it now).

5. **Refresh the frontend filter options.** The `sources` filter comes from the `filter_options_cache`
   materialized view, which nothing refreshes automatically:

   ```sql
   select refresh_filter_options_cache();
   ```

   Until then a new station's snippets are not filterable by source (and a disabled station keeps appearing).

No Supabase schema change is involved: `audio_files` stores `radio_station_name`/`radio_station_code`/
`location_state` per recording, denormalized by the recorder.

Follow-up, deliberately not done yet: 10 stations have produced no audio for months (KENO, KNNR, WURN, WOLS,
KFUE, WNZK, WGSP, WDJA, WYMY, KMRO) and still hold a recorder slot each. Flipping them to `enabled: false` is
a separate, reviewable change.

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
