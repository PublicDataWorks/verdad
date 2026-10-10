@AGENTS.md

## Claude-specific notes

- `.claude/settings.json` runs `.claude/hooks/session-start.sh` on SessionStart (`startup|resume`) in web
  sessions only: it re-links `.venv` to the venv outside the clone (`/opt/verdad/venv`), runs
  `scripts/cloud/setup.sh --core` (timeout 240 s, at most once per VM) only when the Python 3.11 venv, ffmpeg or
  `server/node_modules` is missing or stale, exports `PYTHONPATH=src` and `ENABLE_PREFECT_DECORATOR=false` (and
  `.venv/bin` on `PATH`), lists which credentials are set and prints a read-only auth probe table.
- `.claude/skills/verdad-heuristics-updater/`: use this skill for any change to disinformation categories,
  heuristics or detection prompts (`prompts/`); it knows the bilingual format and the Supabase import step.
- Use plan mode before touching `src/processing_pipeline/*/flows.py`, `supabase/migrations/`, `fly.*.toml`
  or `Dockerfile.*`; those changes affect the production topology.

## Cloud environment

Setup script, network allowlist, and the full env var table (where to get each value, scopes, risks):
`docs/CLOUD_ENVIRONMENT.md`; paste-ready variables: `docs/cloud-env.template`. Re-provision by hand with
`bash scripts/cloud/setup.sh` (idempotent, always exits 0, prints OK/FAILED per tool).

Env vars the environment may provide (all optional; the hook reports which are set, never their values):

- `FLY_API_TOKEN` - flyctl / Machines API auth (org `verdad`); prefer a read-only org token
- `SUPABASE_ACCESS_TOKEN` - supabase CLI and Management API auth; project ref `dzujjhzgzguciwryzwlx`
- `SUPABASE_DB_URL` - Postgres connection string for `psql` (session pooler)
- `PREFECT_API_AUTH_STRING` - `user:password` basic auth for the Prefect API and UI at `https://prefect.fly.dev`
  (VER-384); usage and the unauthenticated endpoints are in `docs/OPERATIONS.md`.
- `SENTRY_AUTH_TOKEN` - a personal token (or internal integration token) with `org:read project:read event:read`,
  plus `alerts:read` to inspect alert rules; org auth tokens only carry `org:ci` and cannot read issues.
  `SENTRY_ORG=verdad-nk` (hook default), optional `SENTRY_URL`. Projects include `recording-worker`,
  `generic-recording-worker`.
- No `GH_TOKEN` needed: the session's GitHub proxy authenticates `git` and REST `gh api repos/PublicDataWorks/verdad/...`
  (the variable reads `proxy-injected`). `gh pr` / `gh issue` use GraphQL, which the proxy rejects with 403
  whatever token is set; use the built-in GitHub tools or `gh api` REST calls instead.
- Pipeline only: `SUPABASE_URL`, `SUPABASE_KEY` (service role), `R2_*`, `GOOGLE_GEMINI_KEY`, `OPENAI_API_KEY`,
  `SEARXNG_URL`, `JINA_API_KEY` (see `.env.sample`). Never `SENTRY_DSN`.

The hook's probe table at session start is the access check: `OK`, `DENIED` (token wrong or lacks scope),
`BLOCKED` (proxy `CONNECT` 403: the host is not in the environment's network allowlist, not an outage), `SKIP`
(variable unset). By hand:

```bash
fly apps list && fly status -a prefect
supabase projects list
psql "$SUPABASE_DB_URL" -c 'select 1'
curl -sS -u "$PREFECT_API_AUTH_STRING" -X POST https://prefect.fly.dev/api/deployments/filter \
  -H 'content-type: application/json' -d '{"limit":1}'   # 401 without -u
sentry-cli info
```

If `fly` is unavailable (its GitHub release download has failed in web sessions), the Machines API works with curl:
`curl -sS "https://api.machines.dev/v1/apps?org_slug=verdad" -H "Authorization: Bearer $FLY_API_TOKEN"` and
`curl -sS "https://api.machines.dev/v1/apps/<app>/machines" -H "Authorization: Bearer $FLY_API_TOKEN"`.
If `supabase` or `psql` is unavailable, SQL goes through the Management API:
`POST https://api.supabase.com/v1/projects/dzujjhzgzguciwryzwlx/database/query` with `SUPABASE_ACCESS_TOKEN`.

Safety: this environment talks to production. Be read-mostly by default (`fly status`, `fly logs`, `SELECT`s).
Confirm with a human before `fly deploy`, `fly machine destroy/restart`, `fly secrets set`, schema migrations
(`supabase db push`, files under `supabase/migrations/`), or any `DELETE`/`UPDATE` on production data.
