# News ledger (VER-367)

## Purpose

Stage 3 runs on `gemini-2.5-pro`, whose knowledge cutoff is January 2025. When the audio describes a real
post-cutoff event (Abelardo de la Espriella inaugurated president of Colombia on 2026-08-07, Keiko Fujimori
inaugurated in Peru on 2026-07-28, Maduro captured on 2026-01-03), the model has no memory of it, SearXNG
often returns nothing on-topic, and the analysis lands on "fabricated".

The news ledger is a curated, dated index of headlines from wire services, public broadcasters and IFCN
fact-checkers. It gives Stage 3 a first evidence source that is trustworthy, carries a real publication date,
and that the pipeline itself never writes to, so it cannot self-poison the way `kb_entries` can (about 98% of
those rows are pipeline-authored).

## Data flow

```
config/news_feeds.yaml
  -> src/news_ledger/feeds.py        load + validate the feed list
  -> src/news_ledger/poller.py       feedparser fetch, URL normalisation, age filter
  -> news_index                      one row per article (unique on url)
  -> OpenAI text-embedding-3-large   batched, L2-normalised
  -> news_index_embeddings           vector(3072), HNSW index on sub_vector(embedding, 512)

Stage 3:
  news_ledger_search(query, published_after?, published_before?)   src/processing_pipeline/stage_3/news_tools.py
  -> search_news_index RPC (two-stage sub-vector search, same shape as search_kb_entries)
  -> {"query", "results": [{url, title, summary, outlet, published_at, credibility_tier, similarity}]}
```

The tool is declared first in `WEB_TOOLS` (`stage_3/executors.py`), and its docstring, which is the tool
description Gemini sees, tells the model to call it before web search. Like `searxng_web_search`, it never
raises: a failure comes back as `{"failed": true, "error": ..., "results": []}`.

`src/news_ledger/flows.py` is the Prefect flow `news_ledger_poller(repeat=False)`: poll every enabled feed,
upsert, embed what is missing, sleep an hour when `repeat=True`.

## How to add a feed

1. Add an entry to `config/news_feeds.yaml`: `name` (unique, stored as `news_index.outlet`), `url` (unique),
   `language` (`es` | `en` | `ar`), `tier` (1 = wire / public broadcaster / IFCN fact-checker, 2 = major
   outlet), and `enabled` (defaults to true).
2. If the feed URL cannot be verified, keep the outlet in the file with `enabled: false` and a comment saying
   what needs checking. That is why AP, Reuters, EFE and AFP Factual are currently disabled.
3. Run the tests: `pytest tests/test_news_feeds.py -q --no-cov`.

Nothing else needs changing: the loader validates the file and the poller reads `enabled_feeds()` on every
iteration, so a config change takes effect on the next deploy.

## Running the poller once locally

Needs `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` in `.env` pointing at a non-production project, and
the migration applied there.

```bash
source .venv/bin/activate
PYTHONPATH=src ENABLE_PREFECT_DECORATOR=false python -c \
  "from news_ledger.flows import news_ledger_poller; news_ledger_poller(repeat=False)"
```

To try a single feed without writing anything, call the pieces directly:

```bash
PYTHONPATH=src python -c \
  "from news_ledger.feeds import enabled_feeds; from news_ledger.poller import fetch_feed, collect_items; \
   from datetime import datetime, timedelta, timezone; f = enabled_feeds()[0]; \
   print(len(collect_items(f, fetch_feed(f.url), datetime.now(timezone.utc) - timedelta(hours=48), 100)))"
```

## Not done in this slice

- The Stage 4 web researcher does not use the ledger yet; only Stage 3 has the tool.
- No backfill: the poller only picks up items from the last 48 hours, so the ledger starts empty and fills
  forward. Backfilling the last 90 days needs per-outlet archive access, not RSS.
- The feed list has not been reviewed against the VER-360 source tiers; `credibility_tier` is a first pass.
- AP, Reuters, EFE and AFP Factual are present but disabled: no verified public feed URL.
- Nothing is deployed and the migration is not applied.

## Deploy checklist

1. Apply `supabase/migrations/20260918000000_news_index.sql` in the Supabase SQL editor, then append its
   version to `supabase/migrations/applied_versions.txt`. (`supabase/database/sql/search_news_index.sql` is
   the loose copy of the function; keep the two in sync.)
2. `feedparser` is a new dependency, so the processing worker image must be rebuilt:
   `fly deploy -c fly.processing_worker.toml`.
3. The new `news_ledger_poller` process group in `fly.processing_worker.toml` and the matching
   `FLY_PROCESS_GROUP` case in `src/processing_pipeline/main.py` are topology changes and need human review
   before deploy.
4. Start the deployment ("News Ledger: Poller") from the Prefect UI or the usual
   `scripts/start_processing.sh` path, and check the first run's summary line in the logs.
