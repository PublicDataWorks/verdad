---
name: verdad-heuristics-updater
description: Transform raw disinformation research into production-ready detection heuristics for the VERDAD audio monitoring pipeline. Handles ingestion from Google Docs, raw notes, or even just a topic name — generates bilingual (Spanish/Arabic) heuristics, updates prompt files, and deploys to Supabase. Use this skill whenever the user mentions VERDAD heuristics, disinformation categories, detection prompts, or wants to add/update/modify any disinformation detection category. Triggers on phrases like "add a new category", "update heuristics", "new disinformation topic", "ingest this Google Doc", or any reference to categories 1-21+ in the VERDAD system. Even if the user just says something like "we need to detect X type of misinformation", this skill applies.
---

# VERDAD Heuristics Updater

## Critical Configuration

- **Supabase Project ID**: `dzujjhzgzguciwryzwlx` — use this for ALL Supabase MCP calls (`execute_sql`, `list_tables`, etc.)
- **Supabase Project Name**: VERDAD
- **Supabase URL**: `https://dzujjhzgzguciwryzwlx.supabase.co`
- **Repo path**: Look for the `prompts/` directory in the current working directory, or check `/Users/j/GitHub/verdad/`

## On Invocation

When this skill triggers, immediately:
1. Determine your environment (Claude Code with file access? Claude.ai with only Supabase MCP? Cowork?)
2. Ask the user what they want to add — a Google Doc URL, raw notes, or a topic idea
3. Read the format templates in `templates/` before generating anything

## Architecture

The VERDAD pipeline has two stages that use heuristics, each optimized differently:

- **Stage 1** (fast flagging): Scans transcriptions to flag potential disinformation. Heuristics are concise — just keywords, detection patterns, and examples. No subcategories in the main prompt.
- **Stage 3** (deep analysis): Evaluates flagged snippets with web search verification. Heuristics are detailed — includes evidence grounding, cultural context, legitimate discussions, red flags, and full subcategories.

Each stage has two files: a **user prompt** (imported to Supabase DB, used at runtime) and a standalone **heuristics.md** (reference file, not imported).

### File Locations (relative to verdad repo root)

| File | Imported to DB? | Subcategories? | Format |
|------|-----------------|----------------|--------|
| `prompts/stage_1/main/detection_user_prompt.md` | Yes | No | Stage 1 |
| `prompts/stage_1/main/heuristics.md` | No (reference) | Yes | Stage 1 |
| `prompts/stage_3/analysis_prompt.md` | Yes | Yes | Stage 3 |
| `prompts/stage_3/heuristics.md` | No (reference) | Yes | Stage 3 |

### Insertion Points

- Stage 1 `detection_user_prompt.md`: Before `## Additional Instructions`
- Stage 1 `heuristics.md`: After the last category's `---`
- Stage 3 `analysis_prompt.md`: Before `### **Additional Instructions**`
- Stage 3 `heuristics.md`: After the last category's `---`

## Workflow

### Step 1: Ingest Source Material

Accept input in any form:
- **Google Doc URL**: Read via `gws docs` CLI or Google Docs MCP. Extract text content, strip formatting artifacts and URLs.
- **Raw text**: Pasted notes, TikTok examples, field observations, radio transcript excerpts.
- **Seed idea**: Even just a topic name like "dental health misinformation" — research and generate comprehensive heuristics from domain knowledge.

### Step 2: Check Current State

Find the current highest category number so you assign the next one correctly:

```bash
grep "### \*\*[0-9]" prompts/stage_1/main/heuristics.md | tail -1
```

Or via Supabase MCP (project ID `dzujjhzgzguciwryzwlx`):
```sql
SELECT substring(user_prompt from '### \*\*(\d+)\.' ) as last_cat
FROM prompt_versions
WHERE stage = 'stage_1' AND sub_stage = 'disinformation_detection' AND is_active = true;
```

### Step 3: Generate Heuristics

Read the format templates before writing:
- **`templates/stage1_format.md`** — concise format for fast detection
- **`templates/stage3_format.md`** — detailed format for deep analysis

Generate both variants of each new category simultaneously — they cover the same content but at different levels of detail.

#### Content Requirements

Every new category needs:

1. **Bilingual content** — Spanish AND Arabic keywords, phrases, and examples throughout. Source material is often Spanish-only; generate Arabic parallels for every item.
2. **Subcategories** — Break the category into specific subtopics (typically 5-15). Each gets its own narratives, evidence, and examples.
3. **Evidence grounding** (Stage 3) — Brief medical/scientific consensus for each subcategory explaining *why* these claims are disinformation.
4. **Cultural context** (Stage 3) — How this disinformation spreads differently in Spanish-speaking vs Arabic-speaking communities (information channels, traditional practices, trust factors).
5. **Legitimate discussions** (Stage 3) — Topics that look like disinformation but aren't, to reduce false positives.
6. **Detection tactics** (Stage 3) — Meta-patterns that signal disinformation regardless of topic: commercial incentives ("link en bio"), censorship claims ("me censuran"), platform migration ("grupo de Telegram"), performative authority ("doctor dice").
7. **Red flags** (Stage 3) — Split into "immediate high-confidence" vs "requires careful analysis."

#### Adapting Source Material

Raw input needs these transformations:
- **Strip links and dates** — Remove verdad.app URLs, TikTok links, timestamps. Use representative examples that capture *patterns*.
- **Restructure** — Convert flat notes into the structured format (Description → Keywords → Heuristics → Examples for Stage 1; full template for Stage 3).
- **Add cross-category notes** — Note overlaps with existing categories (especially 3/COVID, 6/Abortion, 11/Healthcare, 14/Conspiracies).

### Step 4: Update Files

Insert into all four files, matching each file's format. When you have file access (Claude Code / Cowork), use the Edit tool to insert at the documented insertion points.

When you DON'T have file access (Claude.ai), construct the updated `user_prompt` content by:
1. Fetching the current prompt from the database
2. Finding the insertion point in the text
3. Inserting the new category content
4. Deploying the modified prompt back to the database

### Step 5: Deploy to Database

The pipeline reads prompts from the Supabase `prompt_versions` table at runtime.

**Supabase project ID**: `dzujjhzgzguciwryzwlx`

#### Check current versions
```sql
SELECT id, stage, sub_stage, version, is_active, length(user_prompt) as chars
FROM prompt_versions WHERE is_active = true ORDER BY stage, sub_stage;
```

#### Create new version (copy current, insert as inactive)
```sql
INSERT INTO prompt_versions (stage, sub_stage, version, description, created_by,
  system_instruction, user_prompt, output_schema, is_active)
SELECT stage, sub_stage, '{VERSION}', '{DESCRIPTION}', 'heuristics_updater',
  system_instruction, user_prompt, output_schema, false
FROM prompt_versions WHERE id = '{ACTIVE_ID}'
RETURNING id;
```

#### Update the user_prompt with new content

The prompt content is too large (30-125KB) to pass inline via SQL. Use this workaround:

1. Create a temporary SECURITY DEFINER function:
```sql
CREATE OR REPLACE FUNCTION public.temp_import_prompt(p_id uuid, p_user_prompt text, p_token text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  IF p_token != '{RANDOM_TOKEN}' THEN RAISE EXCEPTION 'Invalid token'; END IF;
  UPDATE prompt_versions SET user_prompt = p_user_prompt WHERE id = p_id;
  RETURN jsonb_build_object('success', true, 'id', p_id);
END; $$;
GRANT EXECUTE ON FUNCTION public.temp_import_prompt TO anon;
```
Generate a unique token per session (e.g., `verdad_import_` + random hex).

2. POST the content via REST API:
```python
import requests
requests.post(
    "https://dzujjhzgzguciwryzwlx.supabase.co/rest/v1/rpc/temp_import_prompt",
    headers={"apikey": "{ANON_KEY}", "Content-Type": "application/json"},
    json={"p_id": "{ROW_ID}", "p_user_prompt": updated_content, "p_token": "{RANDOM_TOKEN}"}
)
```

3. Activate and clean up:
```sql
UPDATE prompt_versions SET is_active = false WHERE id = '{OLD_ID}';
UPDATE prompt_versions SET is_active = true WHERE id = '{NEW_ID}';
DROP FUNCTION IF EXISTS public.temp_import_prompt;
```

4. Verify:
```sql
SELECT id, stage, version, is_active,
  user_prompt LIKE '%{CATEGORY_NAME}%' as has_new_category
FROM prompt_versions WHERE is_active = true ORDER BY stage;
```

Repeat for both Stage 1 (`disinformation_detection`) and Stage 3.

### Step 6: Push to GitHub (if file access available)

```bash
git add prompts/stage_1/main/heuristics.md prompts/stage_1/main/detection_user_prompt.md \
       prompts/stage_3/heuristics.md prompts/stage_3/analysis_prompt.md
git commit -m "Add category {N}: {Name} disinformation heuristics"
git push origin main
```

## Gotchas

1. **Stage 1 user prompt has NO subcategories.** Only Description / Keywords / Heuristics / Examples. Subcategories go in the standalone heuristics.md only.
2. **Stage 3 analysis_prompt.md is huge (~2600+ lines).** The insertion point is between the last heuristic and `### **Additional Instructions**`.
3. **Dollar-quoting for SQL.** When passing prompt content via SQL, use PostgreSQL dollar-quoted strings (`$VUP$...$VUP$`). Verify the tag doesn't appear in the content first.
4. **Arabic text.** Renders correctly in markdown. Don't wrap it in special formatting or RTL markers.
5. **Always check current category numbers.** Don't assume the last category is 21 — it changes as categories are added.
6. **RLS blocks the anon key.** The `prompt_versions` table has row-level security. Use the temp SECURITY DEFINER function for updates, then always drop it after.
7. **Cross-category overlap.** Health categories (20, 21) overlap with COVID (3), Abortion (6), Healthcare Reform (11), Conspiracies (14). Note these overlaps in new categories too.
8. **Four files must stay in sync.** Two user prompts (imported to DB) + two standalone heuristics (reference). All four need the new category.
9. **Version format is semver.** Check current active versions before choosing new numbers. Bump minor version for new categories (e.g., 2.1.0 → 2.2.0).
10. **Always drop temp functions.** The SECURITY DEFINER function bypasses RLS — leaving it is a security risk.
