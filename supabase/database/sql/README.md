# `supabase/database/sql/` is historical

These files are hand-applied SQL from before the repo had a usable migration history. They were run by
copy-pasting them into the Supabase SQL editor, in no recorded order, and nothing checks them against the
database. **They are not migrations and are not applied by `supabase db push`.**

The live definitions of everything in here are in
[`supabase/migrations/20260915000000_baseline_public_schema.sql`](../../migrations/20260915000000_baseline_public_schema.sql),
generated from the production database. Read the baseline, not these files, when you need to know what runs
in production.

## Five files no longer match production

The body in the file is not the body in the database:

| File | How production differs |
|---|---|
| `search_related_snippets.sql` | Production has the 5-argument two-stage HNSW version (`p_snippet_id`, `candidate_multiplier`) from PR #54; the file has the older 4-argument sequential-scan version. |
| `update_snippet_comment_count.sql` | Production also filters `AND deleted_at IS NULL`. |
| `get_public_snippet.sql` (`get_public_snippet_function.sql`) | Production reads `title ->> 'english'` / `summary ->> 'english'` after the `alter_title_jsonb` migration. |
| `dismiss_welcome_card.sql` | Production returns `{'status', 'message'}`; the file returns `metadata`. The file has not changed since 2024-11-19, so production was hand-edited. |
| `fetch_a_snippet_that_has_no_embedding.sql` | Production uses `id NOT IN (SELECT snippet FROM snippet_embeddings)`; the file uses a CTE with `NOT EXISTS`. The file's plan is the better one - fixing production forward is a follow-up. |

(`update_snippet_hidden_status.sql` also differs, cosmetically only.)

## Five files are data fixes, not schema

`comment_count_migration.sql`, `like_count_migration.sql`, `upvote_count_migration.sql`,
`label_upvote_count_migration.sql` and `update_last_user_activity.sql` are one-off `UPDATE` backfills (a couple
also create an index). Despite the `_migration` suffix they were never migrations and must not be turned into
any; re-running them would recompute counters over the whole table.

## New schema work does not go here

Put it in `supabase/migrations/` in a file named `YYYYMMDDHHMMSS_short_name.sql` with a full 14-digit
timestamp - never a bare date. See "Database schema and migrations" in [`docs/OPERATIONS.md`](../../../docs/OPERATIONS.md)
for the rules and for what a human runs after a migration PR merges.

## This directory is going away

Deleting it is planned once PRs #73 and #80 (which still modify files in here) have landed. Git history keeps
every body, so nothing is lost. It was deliberately left in place in the PR that added the baseline so those
two PRs do not have to be rebased.
