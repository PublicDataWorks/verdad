---
paths:
  - "supabase/**"
---

# Supabase SQL

## Two directories, only one is a migration history

- `supabase/migrations/` - dated/numbered files (`20241029135348_remote_schema.sql` is the baseline dump;
  the `20260129_*` ones optimize `get_snippets`, `get_filtering_options`, `get_trending_topics` and indexes).
  This is what `supabase db push` would apply.
- `supabase/database/sql/` - ~50 loose function/trigger/index scripts. **Not migrations**: they have no
  ordering, are applied by hand, and nothing records which ones ran. Do not assume the database matches a
  file here; the same function may also exist, in a newer form, inside a migration. When you change a
  function that appears in both places, change both and say so.

Migrations and loose SQL are applied by a human in the Supabase SQL editor. Never run DDL, `supabase db push`,
`DELETE` or `UPDATE` against production from an agent session - `SUPABASE_DB_URL` points at production, so
keep to `SELECT` and `\d`.

## Functions the pipeline depends on

The Python side claims work through reserve-RPCs. Each is a single `UPDATE ... WHERE id = (SELECT ... LIMIT 1
FOR UPDATE SKIP LOCKED) RETURNING row_to_json(...)` that flips the row to `Processing`/`Reviewing` as it
selects; that is the only thing stopping two workers from claiming the same row, so keep the
`FOR UPDATE SKIP LOCKED` and the single-statement shape: `fetch_a_new_audio_file_and_reserve_it`,
`fetch_a_new_stage_1_llm_response_and_reserve_it`, `fetch_a_new_snippet_and_reserve_it`,
`fetch_a_ready_for_review_snippet_and_reserve_it`, `fetch_a_snippet_that_has_no_embedding`. Also
`search_kb_entries`, `find_duplicate_kb_entries`, `sub_vector` and `upsert_prompt_version`.

## Functions the frontend depends on

verdad-frontend calls these from the browser with the anon key, so they are `SECURITY DEFINER` and their
result shape is a public API: `get_snippets`, `get_snippet`, `get_public_snippet`, `get_trending_topics`,
`get_filtering_options`, `get_snippet_labels`, `like_snippet`, `toggle_star_snippet`, `hide_snippet`,
`unhide_snippet`, `upvote_label`, `toggle_upvote_label`, `create_apply_and_upvote_label`,
`undo_upvote_label`, `get_welcome_card`, `dismiss_welcome_card`, `get_landing_page_content`, `get_roles`,
`get_users`, `get_users_by_emails`, `setup_profile`, `search_related_snippets`,
`search_related_snippets_public`. Two RPCs the frontend calls - `get_topic_details` and
`toggle_welcome_card` - have no SQL anywhere in this repo; they exist only in the live database, so do not
treat this directory as a complete picture of the schema.

Most of them guard with `current_user_id := auth.uid()` and `RAISE EXCEPTION 'Only logged-in users can call
this function'`; the `*_public` and landing-page ones deliberately do not. Copy that pattern rather than
relying on RLS, since `SECURITY DEFINER` bypasses it.

Nothing validates these shapes at runtime: the frontend declares them as the `T` in `rpc<T>()` in
`verdad-frontend/src/apis/` with interfaces in `verdad-frontend/src/types/`. If you add, rename or retype a
returned column, update those types in the frontend repo in the same change - a renamed column shows up as
`undefined` in the UI, not as an error.

New functions follow the existing style: `CREATE OR REPLACE FUNCTION ... RETURNS jsonb SECURITY DEFINER AS
$$ ... $$ LANGUAGE plpgsql`, the `auth.uid()` guard, and no explicit `GRANT` (the loose files rely on the
default `public` execute grant; only the knowledge-base tables carry explicit grants).
