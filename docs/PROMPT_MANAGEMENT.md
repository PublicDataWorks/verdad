# Prompt management

How LLM prompts are stored, loaded, changed and tracked in the VERDAD processing pipeline, as of the code on `main` in September 2026. Every statement below was checked against the referenced file; line numbers drift, so treat them as pointers.

Related: [PROMPT_REWRITER_STATUS_AND_PLAN.md](PROMPT_REWRITER_STATUS_AND_PLAN.md) for what is planned to change.

## 1. Overview

- Prompts live in the Supabase table `prompt_versions`. Columns: `id`, `stage`, `sub_stage`, `version`, `system_instruction`, `user_prompt`, `output_schema` (JSONB), `is_active`, `description`, `created_by`, `created_at`, `updated_at`.
- Exactly one row per `(stage, sub_stage)` is meant to be active. Activation is done atomically by the SQL function `upsert_prompt_version` (`supabase/database/sql/upsert_prompt_version.sql`): it inserts the new row as inactive, deactivates the other rows for the same key, then activates the new one.
- Each Prefect flow fetches its prompts once at flow start with `SupabaseClient.get_active_prompt(stage, sub_stage)` (`src/processing_pipeline/supabase_utils.py:110-124`), which selects `is_active = true` for the key and raises `ValueError` if no row matches. Running flows do not pick up changes until they restart. `get_prompt_by_id` (`supabase_utils.py:126-135`) exists but has no callers.
- The files under `prompts/` in git are the source of truth for prompt content. The table only holds what was imported from them. The DDL for `prompt_versions` and the `upsert_prompt_version` function are both in the baseline migration `supabase/migrations/20260915000000_baseline_public_schema.sql`.
- `stage` values come from `PromptStage` (`src/processing_pipeline/constants.py:42-45`): `stage_1`, `stage_3`, `stage_4`. `sub_stage` values come from `Stage1SubStage` (`stage_1/constants.py`) and `Stage4SubStage` (`stage_4/constants.py`); Stage 3 has `sub_stage = NULL`.

## 2. Inventory

The mapping from files to `(stage, sub_stage)`, and the version each entry is at, is `prompts/manifest.json` (read by `src/scripts/prompt_manifest.py`; `import_prompts_to_db.py` derives its `PROMPT_MAPPING` from it). Line numbers in the "Loaded by" column point at where the prompt text is actually used.

| stage / sub_stage | Files under `prompts/` | Loaded by | Notes |
|---|---|---|---|
| `stage_1` / `initial_transcription` | `stage_1/preprocess/initial_transcription_user_prompt.md`, `initial_transcription_output_schema.json` | `stage_1/flows.py:75`; `stage_1/executors.py:42-45` (`Stage1PreprocessTranscriptionExecutor`) | No system instruction. User prompt sent verbatim with the audio file. |
| `stage_1` / `initial_detection` | `stage_1/preprocess/initial_detection_system_instruction.md`, `initial_detection_user_prompt.md`, `initial_detection_output_schema.json` | `flows.py:76`; `executors.py:76-89` (`Stage1PreprocessDetectionExecutor`) | User prompt is a `str.format` template with placeholders `{kb_context}`, `{metadata}`, `{transcription}`. Literal braces in the file would break formatting. |
| `stage_1` / `timestamped_transcription` | `stage_1/main/timestamped_transcription_system_instruction.md`, `timestamped_transcription_user_prompt.md`, `timestamped_transcription_output_schema.json` | `flows.py:77`; `executors.py:234-238` (`GeminiTimestampTranscriptionGenerator`) | Sent verbatim, followed by audio segments. |
| `stage_1` / `disinformation_detection` | `stage_1/main/detection_system_instruction.md`, `detection_user_prompt.md` (890 lines), `detection_output_schema.json` | `flows.py:78`; `executors.py:118-131` (`Stage1Executor`) | `detection_system_instruction.md` is a single 565-byte line with no trailing newline (`wc -l` reports 0). User prompt is a `str.format` template with `{kb_context}`, `{metadata}`, `{timestamped_transcription}`. Contains the 21 heuristic categories as prose. |
| `stage_3` / – | `stage_3/system_instruction.md`, `stage_3/analysis_prompt.md` (2,681 lines), `stage_3/output_schema.json` | `stage_3/flows.py:61`; `stage_3/executors.py:79-84, 104-105, 113` | Not a format template: the executor appends a date / breaking-news block to the user prompt with f-strings. `output_schema` is used only in the second "structure the analysis as JSON" call. Contains the 21 categories with subcategories. |
| `stage_4` / `kb_researcher` | `stage_4/kb_researcher_instruction.md` | `stage_4/flows.py:32`; `stage_4/agents.py:47-52` | ADK `LlmAgent` instruction. |
| `stage_4` / `web_researcher` | `stage_4/web_researcher_instruction.md` | `flows.py:33`; `agents.py:57-62` | ADK agent with the SearXNG MCP toolset. |
| `stage_4` / `reviewer` | `stage_4/reviewer_instruction.md`, `stage_4/output_schema.json` | `flows.py:34`; `agents.py:67-73` | The imported `output_schema` is not read by code; the agent uses the Pydantic model `ReviewAnalysisOutput` (`stage_4/models.py`). |
| `stage_4` / `kb_updater` | `stage_4/kb_updater_instruction.md` | `flows.py:35`; `agents.py:80-85` | Writes to the knowledge base through tools (section 4). |

Not imported:

- `prompts/stage_1/main/heuristics.md` (1,108 lines) and `prompts/stage_3/heuristics.md` (1,371 lines) are reference copies of the heuristics with subcategories. Nothing in `src/` reads them; the heuristics-updater skill keeps them in step with the two user prompts by hand.
- Knowledge-base context is not a file. `retrieve_kb_context` (`src/processing_pipeline/stage_1/kb_context.py:14`) chunks the initial transcription (2,000 chars), embeds the chunks with `text-embedding-3-large`, calls the `search_kb_entries` RPC per chunk (threshold 0.3, 5 matches per chunk), de-duplicates, and formats the facts as a markdown list that fills `{kb_context}`. It is called from `stage_1/tasks.py:147-153` and used for both Stage 1 detection passes (`tasks.py:286-294, 329-331`).

## 3. Changing a prompt

1. Edit the file(s) under `prompts/`. For Stage 1 user prompts, keep the three `{placeholders}` and do not add other literal braces.
2. Bump the entry's `version` (semver) in `prompts/manifest.json`; `import --from-manifest` imports and activates every entry whose manifest version differs from the active database version (this is what CI runs on merge). Alternatively, `import --version X.Y.Z` applies one explicit version string to every entry it imports, so either import everything with a new version or restrict with `--stages`.
3. Import. The script must run from the repo root with `PYTHONPATH=.:src` (it imports `src.processing_pipeline.*`, and those packages import `processing_pipeline.*`), and it reads `SUPABASE_URL` and `SUPABASE_KEY` from the environment or `.env` (`python-dotenv`). The key must be allowed to insert into `prompt_versions`; the anon key is blocked by row-level security.

   ```bash
   PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py import \
       --version 2.4.0 --description "Add category 22" \
       --stages stage_1/disinformation_detection stage_3
   ```

   Flags: `--version` (`X.Y.Z`) or `--from-manifest` (exactly one is required), `--description` (default "Imported from files", max 500 chars), `--no-active` (insert without activating), `--stages` (one or more `stage/sub_stage` labels; default all), `--dry-run` (print what would be imported; still requires the env vars). Rows are created with `created_by = 'import_script'`.
4. Restart the affected flows so they load the new active row.
5. Commit the prompt files.

The heuristics-updater skill (`.claude/skills/verdad-heuristics-updater/SKILL.md`) automates adding a category: it inserts the new text into the four heuristic files, then deploys either through `scripts/deploy_prompts.py` (calls `upsert_prompt_version` with `created_by = 'heuristics_updater'`, only for `stage_1/disinformation_detection` and `stage_3`) or, without a service key, through raw SQL plus a temporary `SECURITY DEFINER` function. The SQL path bypasses the import script and can leave `prompt_versions` ahead of git.

### Checking what is live

- `PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py list` prints every row (stage, sub_stage, version, active, description).
- The active version for a stage is also visible on processed rows through the provenance columns below.

### Checking drift

`PYTHONPATH=.:src python src/scripts/import_prompts_to_db.py diff` compares each manifest entry against the active database row and prints one line per entry: `in sync`, `differs (system_instruction, user_prompt)`, `no active version in db` or `missing local file`. `output_schema` is compared as parsed JSON, and NULL and empty text are treated as equal. `--stages` restricts the check, `--show-diff` prints a unified diff of the differing fields. Exit code 0 means everything is in sync, 1 means drift, 2 means the database could not be reached or the env vars are missing. Run it before and after an import, and whenever prompts were edited directly in the database.

### Provenance

- `stage_1_llm_responses.detection_prompt_version_id` and `.transcription_prompt_version_id` are set from the loaded prompt rows when a file is fully processed (`stage_1/tasks.py:348-349, 362-363`); they are `NULL` when the preprocess pass flags nothing (`tasks.py:311-312`). The two preprocess prompt versions are not recorded anywhere.
- `snippets.stage_3_prompt_version_id` is set by Stage 3 (`stage_3/tasks.py:209`).
- Stage 4 records only `reviewed_by` (a model name) and `reviewed_at` on the snippet (`supabase_utils.py:279-318`); the four Stage 4 prompt version ids are not stored.

## 4. Knowledge base

Schema: `supabase/database/sql/create_knowledge_base.sql`.

- `kb_entries`: `fact`, `related_claim`, `confidence_score`, `valid_from` / `valid_until` / `is_time_sensitive`, `disinformation_categories[]`, `keywords[]`, `version` / `superseded_by` / `previous_version`, `status` (`active` or deactivated with `deactivation_reason`), `created_by_snippet`, `created_by_model`.
- `kb_entry_sources`: URLs backing an entry with a source tier and `relevance_to_claim`.
- `kb_entry_embeddings`: one 3,072-dim embedding per entry; searched by the `search_kb_entries` RPC (`search_kb_entries.sql`) and `find_duplicate_kb_entries`.
- `kb_entry_snippet_usage`: which entry was `used_for_review`, `triggered_creation` or `triggered_update` for which snippet.

Writers: the Stage 4 KB updater agent (off since 2026-09-25, `KB_UPDATER_ENABLED` in `stage_4/constants.py`) through the tools in `src/processing_pipeline/stage_4/tools.py` — `upsert_knowledge_entry` (line 77: dedupes at similarity 0.92, then inserts or supersedes, stores sources, embeds, records usage) and `deactivate_knowledge_entry` (line 223). The `SupabaseClient` methods behind them are in `supabase_utils.py:461-630`. A one-off manual batch was also added on 2026-03-16 (`reports/2026-03-16_downvote_kb_review.md`).

Readers: Stage 1 through `kb_context.py` (section 2) and the Stage 4 KB researcher agent through `search_knowledge_base` (`tools.py:44`). Stage 3 does not read the knowledge base.

## 5. User feedback data path

All of this is SQL and TypeScript; no Python in `src/` reads any of these tables today (grep for `user_like_snippets`, `user_hide_snippets`, `like_count`, `dislike_count`, `comment_count`, `comments` returns nothing).

- Thumbs up/down: the frontend calls the `like_snippet(snippet_id, value)` RPC (`like_snippet_function.sql`), which upserts a row in `user_like_snippets` with `value` in `{-1, 0, 1}`.
- Trigger `update_like_count` (`like_count_trigger.sql`, `update_snippet_like_count.sql`) recomputes `snippets.like_count` and `snippets.dislike_count`.
- Trigger `update_snippet_hidden_status_trigger` (`update_snippet_hidden_status.sql`) inserts into `user_hide_snippets` when a snippet reaches exactly two downvotes, hiding it from the app. Admins can also hide directly with the `hide_snippet` RPC (`hide_snippet.sql`).
- `downvote_review_queue`: the table is in the baseline migration; the trigger that populates it was proposed in the unmerged PR #68 (https://github.com/PublicDataWorks/verdad/pull/68) and is not in this repo.
- Comments: Liveblocks webhooks (`server/src/api/webhooks.ts:44-104`, events `commentCreated` / `commentEdited` / `commentDeleted`) are mirrored into the `comments` table by `server/src/services/commentService.ts`; `update_snippet_comment_count.sql` keeps `snippets.comment_count` current.

The DDL for `user_like_snippets`, `user_hide_snippets`, `comments` and `downvote_review_queue` is in the baseline migration `supabase/migrations/20260915000000_baseline_public_schema.sql`.

## 6. Known gaps

- Heuristics are prose inside two large prompts (890 and 2,681 lines) plus two reference files that must be edited in parallel by hand. Adding or fixing one heuristic means re-importing the whole prompt and bumping every category at once.
- Feedback is collected (likes, dislikes, hides, comments) but never consumed by the pipeline or by anyone editing prompts, other than one manual review in March 2026.
- `src/processing_pipeline/constants.py:48-61` still has file-reading helpers (`get_user_prompt_for_stage_3`, `get_system_instruction_for_stage_3`, `get_output_schema_for_stage_3`, `get_gemini_timestamped_transcription_generation_prompt`). None is called from `src/` or `tests/`, and the last one opens `prompts/Gemini_timestamped_transcription_generation_prompt.md`, which does not exist.
- The heuristics-updater SQL deployment path writes to the database without touching `prompt_versions` via the import script; `diff` (section 3) is the only check that git and the database agree.
- `prompts/stage_4/output_schema.json` is imported but unused by the reviewer agent.

The plan for closing these gaps is in [PROMPT_REWRITER_STATUS_AND_PLAN.md](PROMPT_REWRITER_STATUS_AND_PLAN.md).
