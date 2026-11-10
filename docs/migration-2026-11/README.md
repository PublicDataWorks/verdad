# Migration off Gemini 2.5, Oct 30 to Nov 2 2026 (VER-438, VER-441)

Working notes and tooling from the weekend evaluation that produced PR #159 (configurable models, transcribe-first
Stage 1, word-anchored clips) and PR #160 (detection prompt v4). Kept here so the work survives the session that
produced it; nothing in this folder runs in production.

Start with the handoff doc (quota map, needs, gap, local CLI prompt), linked from Linear VER-441.

## reports/

| File | What it is |
|---|---|
| `transcription_history.md` | Why Stage 1 batches 20 s segments: the history of timestamp failures on 2.5 Flash |
| `code_audit.md` | Every model call site and hardcoded ThinkingConfig before the refactor |
| `transcribe_options.md` | gemini-3.5-transcribe: endpoints, word timestamps via the interactions API, limits, cost |
| `stage1_streamline_design.md` | Design of the transcribe-first Stage 1 and word-boundary clipping |
| `prompt_tuning.md` | Detection prompt variants v1 to v4 and their scores per model |
| `backlog_plan.md`, `requeue_plan.sql`, `requeue_election_stations.sql` | Tiered re-queue of the 22,259-recording backlog; the SQL is a dry run that ends in ROLLBACK |
| `parallel_decisions_eval.md`, `parallel_outreach.md` | Parallel Decisions API as a Stage 3 pre-check (VER-443) |
| `cloudflare_workers_ai_eval.md` | Cloudflare Workers AI (Whisper, Gemma 26B) economics (VER-444) |
| `quota_table.txt` | Service Usage quota snapshot of Oct 31 for pdw-gemini and verdad-factchecking |
| `brief_draft.md` | Early draft of the Paige Bailey briefing; superseded by the prep doc |

## eval/

Running an eval from the repo root, with the repo's Python 3.11 venv (`pip install -r requirements.txt rapidfuzz`):

```bash
python docs/migration-2026-11/eval/fetch_audio.py          # 18 recordings from the public R2 bucket, about 250 MB
SUPABASE_DB_URL=postgres://... python docs/migration-2026-11/eval/build_data.py   # reference data, read-only SELECTs
export GOOGLE_GEMINI_KEY=...                                # a paid-tier key; 3.x models have tiny free quotas
python docs/migration-2026-11/eval/harness.py segments --model gemini-3.5-flash
python docs/migration-2026-11/eval/detection_eval.py --model gemma-4-31b-it
```

The recordings are not committed: `data/manifest.json` maps each `audio_files` id to its path under
https://audio.verdad.app/ and `fetch_audio.py` downloads them into the git-ignored `audio/`. `build_data.py` writes
`data/<audio_file_id>.json` (the production Stage 1 transcripts, flagged snippets and human labels each eval scores
against). Results land in git-ignored `results*/` folders. Set `REPO` only if the repo root is somewhere other than
three levels up.

| File | What it does |
|---|---|
| `build_data.py` | Builds the 18-recording eval set (10 ES, 5 AR, 3 EN) from production rows |
| `harness.py` | Timestamped transcription eval: segments vs transcribe, window similarity, shift test |
| `detection_eval.py` | Stage 1 detection eval per model, backend (API or Vertex), thinking level and prompt dir |
| `stage3_eval.py` | Stage 3 on the 38 clips with the real executor and tool loop |
| `cost_model.py` | Cost per day per lineup at 1x to 10x |
| `parallel_*.py` | Parallel Decisions API probes and metrics |
| `prompts_tuning/` | Detection prompt variants v1 to v4 and `NOTES.md`; v4 is what PR #160 ships |
| `fetch_audio.py` | Downloads the eval recordings from R2 |
| `data/manifest.json`, `snippets_selection.json` | The 18 recordings (10 Spanish, 5 Arabic, 3 English) and the 38 Stage 3 clips |

## quota_pull.py

Re-pulls the per-model quota limits for both projects with a logged-in gcloud. See its docstring.
