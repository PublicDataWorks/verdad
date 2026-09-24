# Operations

Everything below is read from the repo (`fly.*.toml`, `Dockerfile.*`, `scripts/`, `src/processing_pipeline/main.py`).
Items marked **unknown** are not recorded anywhere in the repo; ask a maintainer before relying on them.

## Fly apps

| Fly app (config) | Dockerfile | Entrypoint | Process groups (`FLY_PROCESS_GROUP`) |
|---|---|---|---|
| `prefect` (`fly.prefect.toml`) | `Dockerfile.prefect` (prefecthq/prefect:3.4.24-python3.11 + supercronic + flyctl) | `server`: `scripts/start_prefect_server.sh` (port 4200, health `/api/health`); `cron`: `scripts/start_cron.sh` | `server`, `cron` |
| `processing-worker` (`fly.processing_worker.toml`) | `Dockerfile.processing_worker` (python3.12 + node22 + ffmpeg + `@google/gemini-cli@0.20.0`) | `scripts/trigger_processing_worker.sh` -> waits for `https://prefect.fly.dev/api/health` -> `python src/processing_pipeline/main.py` | `initial_disinformation_detection`, `initial_disinformation_detection_2`, `audio_clipping`, `in_depth_analysis`, `regenerate_timestamped_transcript`, `redo_main_detection`, `undo_disinformation_detection`, `undo_audio_clipping`, `analysis_review`, `analysis_review_2`, `embedding` |
| `recording-worker` (`fly.recording_worker.toml`) | `Dockerfile.recording_worker` (python:3.12-slim + ffmpeg) | `scripts/recording.sh` -> `python src/recording.py` | `max_recorder` (`recorder: max` stations, currently 39, 8 GB), `lite_recorder` (`recorder: lite`, currently 14 enabled, 6 GB) |
| `generic-recording-worker` (`fly.generic_recording_worker.toml`) | `Dockerfile.generic_recording_worker` (ubuntu + Chrome + pulseaudio) | `scripts/generic_recording.sh` -> `python src/generic_recording.py` | `radio_khot`, `radio_kisf`, `radio_krgt`, `radio_wkaq`, `radio_wado`, `radio_waqi` (one machine each; the `process_group` of each `recorder: generic` station in `config/stations.yaml`) |
| `verdad-searxng` (`fly.searxng.toml`) | `Dockerfile.searxng` (searxng/searxng:2026.9.20 + `searxng/config/settings.yml`) | image default | none; serves `https://verdad-searxng.fly.dev` used via `SEARXNG_URL` (stage 3 tools, stage 4 MCP) |
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
- The Prefect API requires basic auth (VER-384, since 2026-09-18): `PREFECT_SERVER_API_AUTH_STRING` on the `prefect`
  app, and the same `user:password` as `PREFECT_API_AUTH_STRING` on `prefect` (cron scripts), `processing-worker`,
  `recording-worker` and `generic-recording-worker`. The Prefect client and CLI read it from the env; raw `curl`
  needs `-u "$PREFECT_API_AUTH_STRING"`. `GET /api/health` and `/api/ready` stay open (Fly health check). The UI
  loads and asks for the same credential. Rotating it is not zero-downtime: Prefect accepts one value, so clients
  and server disagree until all four apps carry the new one. Set it on the four apps back to back (each
  `fly secrets set` restarts that app, which orphans its runs anyway), then recreate the runs as in the restart
  gotchas below. Only the first enablement could go clients first, because a server without auth ignores the header.
- `verdad-server`'s `POST /api/liveblocks-auth` issues a room-scoped Liveblocks token (VER-385): a non-admin gets
  full access to the one snippet room it asked for, and only if that `room` is a `public.snippets.id` uuid the user
  could open (`Processed` and not in `user_hide_snippets`, the `get_snippet` rule) -- anything else answers
  `403 {"error":"Room not found"}`. A request without a `room` (the frontend's inbox
  notifications) gets a token with no room permissions, and users carrying the `admin` role in `public.user_roles`
  still get the `*` wildcard for moderation. Deploy it with `cd server && fly deploy -c fly.server.toml`.
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

1. **Edit `config/stations.yaml` and the snapshots in `tests/test_stations.py` together.** Add an entry with
   `code`, `name`, `url`, `state` and `recorder` (`max` | `lite` | `generic`), or set `enabled: false` on an
   existing one to stop recording it. `code` and `url` must be unique. The tests pin the per-recorder code
   lists, the station count, the Prefect run strings and the set of disabled stations, so `make check` fails
   until the snapshots match the YAML; update them in the same commit. Check your edit locally:

   ```bash
   PYTHONPATH=src python -m stations codes --recorder max     # what the max machine will serve
   PYTHONPATH=src python -m stations prefect-runs             # what start_recording.sh will trigger
   make check
   ```

   `code` is the Prefect deployment name and `url` determines the R2 prefix
   (`radio_<last 6 hex of sha256(url)>/`): renaming a code orphans its deployment, and changing a url moves
   where that station's audio lands.

2. **Check memory sizing** if you added a `recorder: max` station. `max_recorder` runs one ffmpeg process per
   station on a single 8 GB / 8 shared-CPU machine (`lite_recorder` is 6 GB); bump `[[vm]] memory` in
   `fly.recording_worker.toml` in the same PR if the count grows meaningfully. Prefer `lite` when unsure.

3. **A `recorder: generic` station needs more.** It also needs `process_group: radio_<slug>`, a `driver` block
   (unique PulseAudio `sink`/`source`, plus the play-button and video-element CSS selectors of its web player),
   a matching `[processes]` entry and `[[vm]]`/`[scale]` sizing in `fly.generic_recording_worker.toml`, and one
   Fly machine of its own (Chrome + PulseAudio, 2 GB each).

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

The five dead `lite` stations (WOLS, WNZK, WGSP, WYMY, KMRO) were disabled on 2026-09-24. Follow-up, not done
yet: five `max` stations have also produced no audio for months (KENO, KNNR, WURN, KFUE, WDJA) and still hold a
recorder slot each.

## Triggering one stage run against production

Deployment names are `"<flow name>/<deployment name>"` (from `main.py`; note stage 3 differs in case):

```bash
export PREFECT_API_URL=https://prefect.fly.dev/api
export PREFECT_API_AUTH_STRING=user:password   # the Fly secret value; see "Secrets" above
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
  API=https://prefect.fly.dev/api   # every call needs -u "$PREFECT_API_AUTH_STRING" (basic auth, VER-384)
  ID=$(curl -sS -u "$PREFECT_API_AUTH_STRING" "$API/deployments/name/Stage%203%3A%20In-depth%20Analysis/Stage%203%3A%20In-Depth%20Analysis" | jq -r .id)
  curl -sS -u "$PREFECT_API_AUTH_STRING" -X POST "$API/deployments/$ID/create_flow_run" -H 'content-type: application/json' \
      -d '{"parameters": {"repeat": true, "skip_review": false, "snippet_ids": []}}'
  ```

  Per tick the cron creates `STAGE_{1..5}_FLOW_RUNS` runs per stage (Fly secrets on the `prefect` app; production
  currently 4/1/5/1/1). Dead runs stay `Running` in the UI until the next tick cancels them; harmless.
- **`fly secrets set ... -a prefect` (or any `prefect` restart) crashes every running flow run within ~2 min**
  ("Concurrency lease renewal failed"). Do it when nothing targeted is in flight, then recreate the runs as above.
- **OOM leaves zombie runs.** When a worker machine is OOM-killed (`exit_code=137` in `fly machine status`) the
  process restarts but its Prefect runs never resume and keep showing `Running`. Check `fly logs`, not Prefect
  state. The stage 3 machine runs 4 GB for this reason (5 loop runs plus targeted by-id runs).
- **Every restart strands in-flight rows** in `Processing`/`Reviewing`. The stage 3 `on_crashed` hook resets
  only rows named in `snippet_ids`; the pg_cron job `sweep_stuck_snippets` (hourly at :05, migration
  `20260917080000`) puts rows older than 2 h back to `New` / `Ready for review`. `cron.job_run_details` shows
  the runs; `SELECT public.sweep_stuck_snippets()` by hand returns how many rows it moved.
- **Stage 3 polls `New` newest-first**, so old rows never drain on their own; reprocess them by id.
- **`Error` is otherwise terminal.** Nothing in the pipeline re-selects an `Error` row, and because transcription
  is a Stage 3 output a snippet that fails Stage 3 has no text and cannot be found by search. The function
  `public.sweep_retryable_errors(p_batch, p_max_attempts)` (migration `20260918030000`, VER-382) moves a bounded
  batch of retryable rows (fixed VER-363 `KeyError`s, Gemini 503/429/500/empty response, Stage 4 MCP session
  failures; never the deliberate `skipped_backlog_*` or `Intentionally Hidden` parks) back to `New`, or to
  `Ready for review` for `[Stage 4]` failures, incrementing `snippets.analysis_attempts` each time and giving up
  after `p_max_attempts` (default 3). **It is not scheduled by default**: `p_batch` is the Gemini-quota dial
  (VER-379). Enable with `SELECT cron.schedule('sweep_retryable_errors', '*/10 * * * *',
  $$SELECT public.sweep_retryable_errors(200)$$)`, pause with `cron.unschedule`, and run one batch by hand with
  `SELECT public.sweep_retryable_errors(50)`, which returns counts by destination.
- **The 95+ Error backlog drains through Stage 3.** `public.drain_error_backlog_95(p_batch)` (migration
  `20260924100000`, VER-389) moves up to `p_batch` `Error` rows scoring 95+ and recorded since 2026-08-01 back to
  `New`, `[Stage 4]` failures included, so Stage 3 rebuilds the evidence. Each row is drained once and logged in
  `snippet_requeue_log` under batch `drain-95-<utc day>`. Not scheduled by default; schedule, yield query, pause
  and rollback are in `supabase/database/sql/cleanup_2026_09/16_drain_error_backlog_95.sql`.
- **Search hit share is recorded hourly** (VER-402, migration `20260924120000`). pg_cron job
  `record_search_hit_stats` (`7 * * * *`) writes the last full hour's Stage 3 analysis and query hit counts, plus
  Stage 4 search counts, to `public.search_hit_stats`. Only rows recorded in the last 7 days count: old
  reprocessed claims hit less for reasons unrelated to search. When under 60% of analyses (at least 20) have a hit
  two hours running, it posts once per streak to the webhook in Vault secret `ops_alerts_slack_webhook`; switch
  channels with `vault.update_secret`. Backfill with `SELECT public.record_search_hit_stats(h, p_alert => false)
  FROM generate_series(<from>, <to>, interval '1 hour') h`; test the alert with `p_min_share => 1.01` on the last
  hour, then re-run it with the defaults. Pause with `cron.unschedule('record_search_hit_stats')`.
- **Transient Gemini errors are retried** (`src/processing_pipeline/gemini_retry.py`: 429/5xx and empty or
  unparseable output, waits of 30 s, 2 min, 5 min) in Stage 3 and Stage 4; the snippet only reaches `Error`
  after the fourth failure, with that message stored. Rerun those ids once the outage is over.
- **Stage 4 reviews carry a tool record and a citation check** (VER-391) in `snippets.grounding_metadata`:
  `stage_4_tool_record` lists every `searxng_web_search` / `web_url_read` call (query or URL, status, returned URLs;
  the record's `time_range` is null since VER-392 hid that argument from the Stage 4 searcher),
  every `search_knowledge_base` call (curated entries' source URLs) and `observed_urls` (`url_key` of everything the
  tools put in front of the model); `stage_4_citation_check` lists every URL in the reviewer's visible text with
  `observed` true/false and the `unobserved` ones (neither a tool returned them nor the Stage 3 record holds them).
  `upsert_knowledge_entry` rejects an unobserved URL as a KB source. The check caps the scores at 40 with a
  `[Citation check]` note for any of its `reasons`: an unobserved article URL in the reviewer's text; an
  unobserved article URL in the web researcher's prose (`web_research_unobserved`, VER-393; recorded but not
  capped when `evidence_backed` is true, i.e. `stage_4_verification_evidence.admissible_contradicting`, VER-405);
  a fabricated /
  `verified_false` verdict with nothing retrieved in the session, i.e. no web search with results, no page read,
  no curated KB source (`retrieval`, VER-369 item 2; the Stage 3 record is the evidence gate's business, not
  this rule's). Setting `CITATION_CHECK_CAPS` (`stage_4/constants.py`, on since 2026-09-22) to `False` switches
  all three back to record-only. The check's `original_*` are the scores as received (already 40 when the
  evidence gate fired first; the gate's own `original_*` hold the pre-gate values). `evidence_gate` is stored
  only when it applied; the citation check always. To undo a period of capping, run
  `supabase/database/sql/rollback/2026-09-22_stage_4_citation_check_restore.sql`.
  `stage_4_verification_evidence` (VER-396) is the source list from the fenced `evidence` block that
  `stage_4/web_researcher` 1.1.0 writes at the end of its report, each contradicting result marked
  `url_observed_in_tools` against the tool record, plus `admissible_contradicting` (whether one of them passes
  the gate's URL and date rules) and `dropped` (entries that failed validation). The gate judges the Stage 3
  record and these results together, so a review that read a contradicting article a tool returned is not
  capped for lack of a Stage 3 source; a URL no tool returned still never counts. Rows reviewed before 1.1.0
  have no such key.
- **The web researcher's first model turn is forced to be a `searxng_web_search` call** (VER-406, `force_first_search`
  in `stage_4/agents.py`): on Flash the agent otherwise skipped the tools in about half of the reviews and narrated a
  search report from memory. After one tool answer the model chooses freely again.
- **A transient DB error on the fetch-work RPC no longer kills the stage loop** (VER-378): statement timeout
  (`57014`), lock/deadlock, server restart (`57P01`-`57P03`), any class-08 connection error, PostgREST's own
  `PGRST000`-`PGRST002` (cannot reach Postgres / schema cache reloading after DDL) or gateway 502/503/504/520/522/524
  reads as "no work" and the loop
  retries after its 60 s sleep; before, the run failed and the stage sat idle until the next cron tick. Any other
  error (a 500 included) still fails the run. Production DDL still pushes the pipeline's queries past their
  timeout, so expect a dip while it runs.
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
- The Prefect API and UI (`https://prefect.fly.dev`) sit behind basic auth (`PREFECT_API_AUTH_STRING`, VER-384);
  the only anonymous endpoints are `GET /api/health` and `/api/ready`.

## Database schema and migrations

`supabase/migrations/` is the only place schema changes belong. It holds the baseline, one comment-only placeholder
per version production has already applied (29), and `applied_versions.txt`.

- **`20260915000000_baseline_public_schema.sql`** is a generated snapshot of the live `public` and `profiles`
  schemas (33 tables, 1 materialized view, 3 enums, 54 functions, 22 triggers, 59 non-constraint indexes, RLS
  on all 33 tables, 16 policies, grants and comments; regenerated 2026-09-17 before it was marked applied). It was produced by `scripts/dump_schema_baseline.py`, which
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
  that every manifest version has a file and that files up to the baseline are in the manifest (newer files are
  pending until applied and repaired). `make migrations-manifest` refreshes it and `make baseline-check` regenerates the
  baseline and diffs it against the committed file (both need `SUPABASE_ACCESS_TOKEN`).
- What the baseline does not carry: object ownership, `ALTER DEFAULT PRIVILEGES`, `REVOKE`s, column-level grants,
  and grants to roles other than `anon`, `authenticated` and `service_role`. On a rebuilt database the 31
  `SECURITY DEFINER` functions therefore run as whoever applied the migration, not necessarily production's owner.
- `supabase/database/sql/` is historical hand-applied SQL, not migrations - see the README in that directory.

### Rules for new migrations

- One file per change in `supabase/migrations/`, named `YYYYMMDDHHMMSS_short_name.sql` with a **full 14-digit
  timestamp**. Never a bare date: `supabase` parses the leading digits as the version, so `20260914_a.sql` and
  `20260914_b.sql` are both version `20260914` and `supabase db push` fails on the `schema_migrations` primary
  key after the first one. Open PR #73 still uses bare dates.
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

If a later migration (e.g. PR #73 or `20260917034500_sources_feed_items.sql`) was applied by hand in the
meantime, `migration repair --linked --status applied` its 14-digit version too.

## Logs and monitoring

- Machine stdout/stderr: `fly logs -a processing-worker` (add `--machine <id>` for one process group; ids from
  `fly status -a <app>`). Same for `recording-worker`, `generic-recording-worker`, `prefect` (cron output lives here).
- Prefect UI: `https://prefect.fly.dev` (the `prefect` app exposes port 4200 over HTTPS). Flows use `log_prints=True`,
  so every `print()` in `src/` appears in the flow run logs. The UI asks for the `PREFECT_API_AUTH_STRING` credential.
- Sentry: `sentry_sdk.init(dsn=SENTRY_DSN)` in the three entrypoints. Project/org: **unknown**.
- Data-level health: row `status` columns (`New`, `Processing`, `Processed`, `Error`, `Ready for review`, `Reviewing`)
  on `audio_files`, `stage_1_llm_responses`, `snippets`; `error_message` holds the exception text.
