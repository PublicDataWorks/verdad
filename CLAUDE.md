@AGENTS.md

## Claude-specific notes

- `.claude/settings.json` runs `.claude/hooks/session-start.sh` on SessionStart in web sessions only: it creates
  `.venv`, installs `requirements.txt` and ffmpeg, installs the `flyctl` and `supabase` CLIs, and exports
  `PYTHONPATH=src` and `ENABLE_PREFECT_DECORATOR=false` for the session.
- `.claude/skills/verdad-heuristics-updater/`: use this skill for any change to disinformation categories,
  heuristics or detection prompts (`prompts/`); it knows the bilingual format and the Supabase import step.
- Use plan mode before touching `src/processing_pipeline/*/flows.py`, `supabase/migrations/`, `fly.*.toml`
  or `Dockerfile.*`; those changes affect the production topology.

## Cloud environment

Env vars the Claude Code web environment may provide (all optional; the hook reports which are set, never their values):

- `FLY_API_TOKEN` - flyctl auth (org `verdad`)
- `SUPABASE_ACCESS_TOKEN` - supabase CLI auth; project ref `dzujjhzgzguciwryzwlx`
- `SUPABASE_DB_URL` - Postgres connection string for `psql`
- `PREFECT_API_AUTH_STRING` - `user:password` basic auth for the Prefect API and UI at `https://prefect.fly.dev`
  (VER-384); usage and the unauthenticated endpoints are in `docs/OPERATIONS.md`. A proxy `CONNECT` 403 on that
  host is the environment's network policy, not an outage.
- Pipeline only: `SUPABASE_URL`, `SUPABASE_KEY`, `R2_*`, `GOOGLE_GEMINI_KEY`, `OPENAI_API_KEY`, `SEARXNG_URL` (see `.env.sample`)

Verify access:

```bash
fly apps list && fly status -a prefect
supabase projects list
psql "$SUPABASE_DB_URL" -c 'select 1'
curl -sS -u "$PREFECT_API_AUTH_STRING" -X POST https://prefect.fly.dev/api/deployments/filter \
  -H 'content-type: application/json' -d '{"limit":1}'   # 401 without -u
```

If `fly` is unavailable (GitHub release downloads are blocked in the web sandbox), the Machines API works with curl:
`curl -sS "https://api.machines.dev/v1/apps?org_slug=verdad" -H "Authorization: Bearer $FLY_API_TOKEN"` and
`curl -sS "https://api.machines.dev/v1/apps/<app>/machines" -H "Authorization: Bearer $FLY_API_TOKEN"`.

Safety: this environment talks to production. Be read-mostly by default (`fly status`, `fly logs`, `SELECT`s).
Confirm with a human before `fly deploy`, `fly machine destroy/restart`, `fly secrets set`, schema migrations
(`supabase db push`, files under `supabase/migrations/`), or any `DELETE`/`UPDATE` on production data.
