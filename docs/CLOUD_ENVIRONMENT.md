# Claude Code on the web: VERDAD environment

How to configure the claude.ai cloud environment that Claude Code on the web sessions run in for this repo.
Three things are configured in the environment dialog at claude.ai/code: the **setup script**, the
**network access** level, and the **environment variables**. The repo supplies the rest:
`scripts/cloud/setup.sh` (provisioning) and `.claude/hooks/session-start.sh` (per-session env + auth probes).

Platform facts below are from the Claude Code docs as of 2026-10-09
([cloud environments](https://code.claude.com/docs/en/cloud-environments),
[hooks](https://code.claude.com/docs/en/hooks)). Items marked *(unverified)* were not observed in a real
cloud session.

## How the pieces fit

| Piece | Runs | Does |
|---|---|---|
| Environment setup script (`bash scripts/cloud/setup.sh \|\| true`) | As root on Ubuntu 24.04, before Claude Code starts, on the first session of the environment. If it finishes in roughly 5 minutes the filesystem is snapshotted and later sessions skip it. The snapshot is rebuilt when the script or the allowed hosts change, or after about 7 days. | apt packages, Python 3.11 `.venv` with `requirements.txt` + pre-commit, `npm ci` in `server/`, flyctl, supabase CLI, sentry-cli, gh. Always exits 0 and prints an OK / FAILED / SKIP table plus versions. |
| SessionStart hook (`.claude/hooks/session-start.sh`) | On `startup` and `resume` (matcher `startup\|resume`) in web sessions (`CLAUDE_CODE_REMOTE=true`); a no-op locally. Repo hooks only load when the session has a single repository. | Runs `setup.sh --check`; only when the core (Python 3.11 venv, ffmpeg, server deps) is missing or stale does it run `setup.sh --quiet --core` under `timeout 240`, at most once per VM. Writes `PATH`, `PYTHONPATH=src`, `ENABLE_PREFECT_DECORATOR=false` and `SENTRY_ORG` (default `verdad-nk`) to `$CLAUDE_ENV_FILE`. Lists which credentials are set (names only) and runs read-only auth probes. |

A non-zero setup script fails the session, which is why `setup.sh` never exits non-zero and the pasted line
still ends in `|| true`.

Retries are bounded. The hook never installs the optional CLIs (flyctl, supabase, sentry-cli, gh): `--core`
skips them. Its core fallback runs at most once per VM: before running it the hook writes
`/tmp/verdad-setup-attempted` (holding the kernel boot id and a timestamp), and while that stamp matches the
current boot, later sessions and resumes on the same VM print "setup already attempted on this VM" and the
path of the last attempt's output (`/tmp/verdad-setup-hook.log`) instead of running it again. A fresh VM has no
stamp, so it gets one attempt. To retry: `bash scripts/cloud/setup.sh` by hand (everything, no timeout), or
`VERDAD_SETUP_FORCE=1` in the environment variables (clears the stamp and re-runs the core step on every
session while it is set, so remove it afterwards). `VERDAD_SKIP_PROBES=1` skips the auth probes.

## 1. Setup script

Paste into the environment's **Setup script** field:

```bash
cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || cd /home/user/verdad 2>/dev/null || true
bash scripts/cloud/setup.sh || true
```

*(unverified)* The working directory and clone path the setup script runs in are not documented; the first
line is a guard. If the repo is not found the script cannot run, and the SessionStart hook provisions on the
first session instead, which is slower but still works (the hook timeout is 600 s by default).

What it installs and how, in order of preference (every route avoids being GitHub-release-only where an
alternative exists):

| Tool | Route | Fallback when it fails |
|---|---|---|
| ffmpeg, postgresql-client, jq, curl, unzip, git, build-essential, libpq-dev | apt (only the missing ones) | per-package retry |
| uv | preinstalled in the cloud image; else `pip install uv` from PyPI | `python -m venv` |
| Python 3.11 | existing `python3.11` / pyenv / `uv python find` > apt > deadsnakes PPA > `uv python install 3.11` | none: venv step reports FAILED |
| `.venv` | `uv pip install -r requirements.txt pre-commit` (rebuilt if `.venv` is not 3.11; stamp = hash of requirements) | pip |
| Node | image's Node 22; else apt `nodejs npm` (18 on Ubuntu 24.04: `tsc` works, vitest's vite needs >= 20) | server step skipped |
| `server/node_modules` | `npm ci` (stamp = hash of `package-lock.json`) | reported FAILED |
| flyctl | pinned GitHub release `v0.4.103`, checksum-verified against the release `checksums.txt` | Machines API with curl (CLAUDE.md, "Cloud environment") |
| supabase CLI | npm `supabase@2.117.0` (its postinstall downloads the binary from GitHub releases) | `psql "$SUPABASE_DB_URL"`, or the Management API `POST /v1/projects/<ref>/database/query` |
| sentry-cli | npm `@sentry/cli@2` (binary ships as an npm optional dependency) | PyPI `sentry-cli` via `uv tool install` |
| gh | image's gh; else apt | none |
| prefect CLI | comes with the venv (`.venv/bin/prefect`) | - |

Python 3.11 is a hard requirement: prefect 3.4.24 has no 3.14 wheel and pydub needs the stdlib `audioop`
module, which is gone in 3.13.

## 2. Network access

Use **Custom**, keep "include the default allowlist" on, and add the hosts below. The default Trusted list
already covers PyPI, npm, Ubuntu archives, `*.googleapis.com` (Gemini), `*.r2.cloudflarestorage.com` and the
GitHub release hosts (`objects.githubusercontent.com`, `release-assets.githubusercontent.com`). It does **not**
cover Fly, Supabase, Sentry, OpenAI or Jina. "Full" also works but gives the session unrestricted egress with
production credentials in its environment.

```
api.machines.dev
api.fly.io
fly.io
*.fly.dev
api.supabase.com
supabase.com
*.supabase.co
*.pooler.supabase.com
sentry.io
*.sentry.io
downloads.sentry-cdn.com
api.openai.com
s.jina.ai
ppa.launchpadcontent.net
```

| Host | Why (from the code) |
|---|---|
| `api.machines.dev`, `api.fly.io`, `fly.io` | flyctl and the Machines API fallback (`fly status`, `fly logs`, apps/machines listing) |
| `*.fly.dev` | `prefect.fly.dev` (Prefect API/UI, basic auth), `verdad-searxng.fly.dev` (`SEARXNG_URL`, stage 3/4 search) |
| `api.supabase.com`, `supabase.com` | supabase CLI, `scripts/dump_schema_baseline.py` (`make migrations-manifest`, `make baseline-check`), Management API SQL |
| `*.supabase.co` | `SUPABASE_URL` REST (pipeline, `run_stage.py`, prompt import/diff/eval) and the direct DB host |
| `*.pooler.supabase.com` | `SUPABASE_DB_URL` through the Supavisor pooler (the direct `db.<ref>.supabase.co` host is IPv6-only) |
| `sentry.io`, `*.sentry.io` | sentry-cli and the Sentry API (`us.sentry.io` region, org `verdad-nk`) |
| `downloads.sentry-cdn.com` | sentry-cli's binary download when the npm optional dependency is not used |
| `api.openai.com` | embeddings (stage 5, KB retrieval) in `run_stage.py` / `evaluate_prompt.py` runs |
| `s.jina.ai` | stage 3 `jina_web_search` fallback (only when `JINA_API_KEY` is set) |
| `ppa.launchpadcontent.net` | deadsnakes PPA, only if the image lacks Python 3.11 and uv cannot download one |

Notes:

- All egress goes through an HTTP(S) proxy. A host that is not allowlisted fails with a proxy `CONNECT`
  403; the hook's probe table reports that as `BLOCKED` (network policy), not as a credential problem.
- *(unverified)* `psql` speaks raw TCP to port 5432/6543 and may not traverse the HTTP proxy even when the
  host is allowlisted. If the `psql` probe fails while `supabase-api` passes, use the Management API
  `POST /v1/projects/dzujjhzgzguciwryzwlx/database/query` with `SUPABASE_ACCESS_TOKEN`.
- GitHub release downloads (flyctl, the supabase CLI binary) have been observed failing in earlier VERDAD web
  sessions even though the release hosts are on the default list; GitHub traffic goes through a separate
  GitHub proxy. The fallbacks above cover it.
- Linear and Slack are used through MCP connectors, not from inside the VM, so they need no entry here
  *(assumption)*. Add `api.linear.app` / `slack.com` only if a task calls their APIs with curl.

## 3. Environment variables

Paste `docs/cloud-env.template` into the environment's variables field, then uncomment and fill in only what
the session needs. Leave unused lines commented rather than `KEY=` with no value: an empty variable is still
set, and `python-dotenv` does not override an existing variable, so it would mask a value from `.env`. The format is `.env` style, one `KEY=value` per line. In an unquoted value `#` starts a comment, so
keep comments on their own lines. **Everyone who can use the environment can read these values**, and the
session runs against production: prefer read-only, narrowly scoped tokens, and leave a variable empty when the
work does not need it. The hook lists which names are set at session start; it never prints values.

### Ops access (what most cloud sessions need)

| Variable | Needed for | Where to get it | Risk / scope |
|---|---|---|---|
| `FLY_API_TOKEN` | flyctl and the Machines API (`fly status`, `fly logs`, machine listing) | `fly tokens create readonly verdad` for a read-only org token (check `fly tokens create --help`; flyctl versions differ). `fly tokens create org -o verdad` only when the task must deploy or restart. `fly tokens create deploy -a <app>` for one app. | An org token can deploy, restart, and set secrets on every app. CLAUDE.md requires human confirmation before any of that regardless. |
| `SUPABASE_ACCESS_TOKEN` | supabase CLI (`projects list`, `db` commands, `migration list`), `make migrations-manifest` / `baseline-check`, Management API SQL | Supabase dashboard > Account > Access tokens (personal access token) | Account-wide: management access to **every** project that account can see, including running arbitrary SQL. Use a token from an account that is a member of only the VERDAD org, and revoke it when no longer needed. |
| `SUPABASE_DB_URL` | `psql` against production | Supabase dashboard > project `dzujjhzgzguciwryzwlx` > Connect > Session pooler URI (IPv4) | With the `postgres` user this is full read/write. Prefer a dedicated read-only role (creating one is a production change; get approval first). |
| `PREFECT_API_AUTH_STRING` | Prefect API and UI basic auth (`user:password`, VER-384), `prefect` CLI | The value set as the Fly secret on `prefect`, `processing-worker`, `recording-worker`, `generic-recording-worker`. `fly secrets list` shows only a digest; get the value from whoever holds it. | Full control of the Prefect server: can cancel runs and trigger deployments against production. |
| `PREFECT_API_URL` | Points the `prefect` CLI at production: `https://prefect.fly.dev/api` | constant | Leave empty unless the task drives Prefect; with it set, any `prefect` command talks to production. |
| `SENTRY_AUTH_TOKEN` | sentry-cli and the Sentry API (issues, events for `recording-worker`, `generic-recording-worker` and the other projects) | Sentry > Settings > Account > Personal Tokens (or an org auth token / internal integration) with scopes `org:read`, `project:read`, `event:read` | Read-only with those scopes. Add `event:write` only to resolve issues. |
| `SENTRY_ORG` | sentry-cli default org | `verdad-nk` (the hook defaults it) | none |
| `SENTRY_URL` | sentry-cli / API base URL | optional; default `https://sentry.io`. Set `https://us.sentry.io` if API calls ask for the region URL. | none |
| `GH_TOKEN` | `gh` CLI beyond what the GitHub proxy provides (PR comments, workflow runs) | GitHub > Settings > Developer settings > fine-grained token, repository `PublicDataWorks/verdad` only | Optional. git push/pull already works through the session's GitHub proxy. |

### Pipeline access (only for running stages, prompt import/diff/eval)

These are what `scripts/run_stage.py`, `src/scripts/import_prompts_to_db.py` and `src/scripts/evaluate_prompt.py`
read (`.env.sample` has one line per variable). Tests need none of them: `tests/conftest.py` sets dummies.
`run_stage.py` refuses the production project unless `--allow-production` is passed, and the prompt
importer writes the `prompt_versions` table, which CI normally does on merge.

| Variable | Needed for | Where to get it | Risk / scope |
|---|---|---|---|
| `SUPABASE_URL` | every pipeline script | `https://dzujjhzgzguciwryzwlx.supabase.co` (dashboard > Project settings > API) | none on its own |
| `SUPABASE_KEY` | `SupabaseClient` | dashboard > Project settings > API keys > **service_role** (Fly secret on `processing-worker` / `recording-worker`) | **Service role: bypasses RLS, full read/write on all data.** Highest-risk value in this list. Only set it for a task that runs pipeline code against production. |
| `SUPABASE_ANON_KEY` | only `.claude/skills/verdad-heuristics-updater/scripts/deploy_prompts.py` | dashboard > API keys > anon | low (public key, RLS applies) |
| `GOOGLE_GEMINI_KEY` | stages 1, 3, 4 and `evaluate_prompt.py` | Google AI Studio / GCP project that holds the production key (Fly secret on `processing-worker`) | billable; shares the production Gemini quota (VER-379). A separate key keeps evals off the pipeline's quota. |
| `OPENAI_API_KEY` | stage 5 embeddings, KB retrieval | OpenAI dashboard > API keys (project-scoped key) | billable |
| `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | audio download/upload in stages 1-3 | Cloudflare dashboard > R2 > Manage API tokens. A token with Object Read only on the bucket is enough for analysis runs. | write access can overwrite or delete recordings |
| `SEARXNG_URL` | stage 3 tools, stage 4 web researcher | `https://verdad-searxng.fly.dev` | none |
| `JINA_API_KEY` | optional stage 3 Jina fallback (VER-415) | Jina dashboard | spends prepaid tokens |

Do **not** set `SENTRY_DSN` in the cloud environment: local runs would report into production Sentry.
`FLY_PROCESS_GROUP` and `ENABLE_PREFECT_DECORATOR` are not credentials; the hook sets
`ENABLE_PREFECT_DECORATOR=false`. `GOOGLE_API_KEY` is derived from `GOOGLE_GEMINI_KEY` by stage 4.

### Which Fly app holds which secret

From the code (`os.getenv` in `src/`, `process.env` in `server/src/`); confirm with `fly secrets list -a <app>`,
which lists names and digests, never values:

| App | Secrets the code reads |
|---|---|
| `processing-worker` | `SUPABASE_URL`, `SUPABASE_KEY`, `R2_*`, `GOOGLE_GEMINI_KEY`, `OPENAI_API_KEY`, `SEARXNG_URL`, `JINA_API_KEY`, `SENTRY_DSN`, `PREFECT_API_AUTH_STRING` |
| `recording-worker`, `generic-recording-worker` | `SUPABASE_URL`, `SUPABASE_KEY`, `R2_*`, `SENTRY_DSN`, `PREFECT_API_AUTH_STRING` |
| `prefect` | `PREFECT_SERVER_API_AUTH_STRING`, `PREFECT_API_AUTH_STRING`, `FLY_MACHINE_IDS`, `STAGE_{1..5}_FLOW_RUNS`, `BATCH_SIZE`, `DELAY_BETWEEN_BATCHES`, flyctl auth for `restart_all.sh` (how it is provided is unknown, see docs/OPERATIONS.md) |
| `verdad-server` | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `LIVEBLOCKS_SECRET_KEY`, `LIVEBLOCKS_WEBHOOK_SECRET`, `RESEND_API_KEY`, `SLACK_NOTIFICATION_EMAIL` (none needed for `npm test` / `tsc`) |

CI (GitHub Actions secrets, not the cloud environment): `FLY_API_TOKEN` (deploy token for `processing-worker`),
`CLAUDE_CODE_OAUTH_TOKEN`, and the job's `GITHUB_TOKEN`.

## 4. Checking a session

The hook's output appears at the top of every web session:

```
[session-start] core tooling ready (Python 3.11.x, ffmpeg present)
[session-start] env set:   FLY_API_TOKEN SUPABASE_ACCESS_TOKEN ...
[session-start] env unset: ...
[session-start] auth probes (read-only, 12s timeout each):
  fly-api        OK       HTTP 200
  supabase-cli   OK       supabase projects list
  psql           FAILED   select 1 (TCP egress or credential; ...)
  prefect        BLOCKED  proxy refused CONNECT: host not in the environment's network allowlist
  sentry-api     OK       HTTP 200
```

Probes: Machines API `GET /v1/apps?org_slug=verdad` (and `fly auth whoami` if flyctl is installed; org tokens
may not support whoami, so the API row decides), `supabase projects list` (or `GET api.supabase.com/v1/projects`),
`psql -c 'select 1'`, Prefect `POST /api/deployments/filter` with `-u`, Sentry
`GET /api/0/organizations/verdad-nk/` plus `sentry-cli info`, and `gh auth status`. All are reads.

`BLOCKED` means add the host to the network allowlist; `DENIED` means the token is wrong or lacks scope;
`SKIP` means the variable is not set. To re-provision by hand: `bash scripts/cloud/setup.sh`.
