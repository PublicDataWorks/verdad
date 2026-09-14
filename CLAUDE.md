# VERDAD backend

Python 3.11+ Prefect pipeline (recording -> stage 1-5 analysis) on Fly.io, data in Supabase (Postgres), audio in Cloudflare R2.

- Install: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (done by `.claude/hooks/session-start.sh` on the web)
- Test: `pytest tests/path/test_x.py` (full run: `pytest`, coverage gate 90%)
- Lint/format: `flake8 --max-line-length=120 src tests`, `black --line-length 120 src tests`, `isort --profile black --line-length 120 src tests`
- Fly apps: `fly.prefect.toml` (prefect), `fly.recording_worker.toml`, `fly.generic_recording_worker.toml`, `fly.processing_worker.toml`, `fly.searxng.toml`, `fly.dev.toml`, `server/fly.server.toml`

## Cloud environment

Env vars the Claude Code web environment may provide (all optional; the hook reports which are set, never their values):

- `FLY_API_TOKEN` - flyctl auth (org `verdad`)
- `SUPABASE_ACCESS_TOKEN` - supabase CLI auth; project ref `dzujjhzgzguciwryzwlx`
- `SUPABASE_DB_URL` - Postgres connection string for `psql`
- Pipeline only: `SUPABASE_URL`, `SUPABASE_KEY`, `R2_*`, `GOOGLE_GEMINI_KEY`, `OPENAI_API_KEY`, `SEARXNG_URL` (see `.env.sample`)

Verify access:

```bash
fly apps list && fly status -a prefect
supabase projects list
psql "$SUPABASE_DB_URL" -c 'select 1'
```

Safety: this environment talks to production. Be read-mostly by default (`fly status`, `fly logs`, `SELECT`s).
Confirm with a human before `fly deploy`, `fly machine destroy/restart`, `fly secrets set`, schema migrations
(`supabase db push`, files under `supabase/migrations/`), or any `DELETE`/`UPDATE` on production data.
