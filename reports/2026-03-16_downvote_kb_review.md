# Downvote Review & Knowledge Base Update Report

**Date:** March 16, 2026
**Performed by:** Claude Opus 4.6 (automated review with human approval)
**Reviewed by:** [pending colleague review]

---

## Executive Summary

Systematic review of all downvoted snippets in the VERDAD pipeline, resulting in 78 newly hidden snippets and 21 new knowledge base entries to prevent future false positive errors. All 21 entries were independently fact-checked by verification agents and 9 corrections were applied before finalization. The review revealed that the majority of downvoted snippets were **incorrectly flagged as disinformation** — they were actually reporting on real events that the pipeline's knowledge base didn't yet know about.

---

## How This Was Done

### Phase 1: Discovery & Analysis

1. **Queried `user_like_snippets`** for all rows with `value = -1` (downvotes), joined against `snippets` and `user_hide_snippets` to find which downvoted snippets were still visible.
2. **Found 135 total downvoted snippets**: 57 already hidden (auto-hide trigger fires at 2 downvotes), 78 still visible with 1 downvote each.
3. **Retrieved full snippet data** (`title`, `summary`, `explanation`, `disinformation_categories`, `confidence_scores`) for all 78 visible snippets.
4. **Grouped snippets by theme** using title keyword analysis, producing 13 topic clusters (Pope/Vatican, Venezuela/Maduro, Elections, Gulf of Mexico, COVID/Vaccines, etc.).

### Phase 2: Hiding Snippets

5. **Inserted all 78 into `user_hide_snippets`** with a single SQL statement:
   ```sql
   INSERT INTO user_hide_snippets (snippet)
   SELECT DISTINCT s.id
   FROM snippets s
   JOIN user_like_snippets uls ON uls.snippet = s.id
   WHERE uls.value = -1
   AND NOT EXISTS (SELECT 1 FROM user_hide_snippets uhs WHERE uhs.snippet = s.id)
   ON CONFLICT (snippet) DO NOTHING;
   ```
   The `user` column was left NULL (it's nullable) since this was a system-level operation, not a user-initiated hide.

### Phase 3: KB Gap Analysis

6. **Checked existing KB entries** against all 13 topic groups. Found that the KB already had strong coverage for several topics (Pope Leo XIV, Maduro capture, Assad regime fall, Marco Rubio as SoS, María Corina Machado Nobel Prize).
7. **Identified 21 gaps** — facts that were NOT in the KB but would have prevented the false positive errors.
8. **Checked for linked KB entries**: Only 3 existing KB entries were linked to the downvoted snippets (all from one snippet about the 2028 election conspiracy). No KB entries linked to already-hidden snippets.

### Phase 4: Research (Parallel Subagents)

9. **Launched 4 parallel research agents**, each assigned a topic cluster:
   - Agent 1: Pope/Vatican + Syria/Assad + South Korea
   - Agent 2: Venezuela/Maduro political facts
   - Agent 3: Gulf of Mexico + Tariffs + COVID + Immigration
   - Agent 4: Israel/Palestine + Russia/Ukraine + Notable events + Government appointments

   Each agent used web search to find authoritative sources (Reuters, AP, NPR, official government sites, fact-checkers) and produced structured KB entry data with: fact text, confidence score, categories, keywords, related claim, source URL, source name, source type, and time-sensitivity flags.

### Phase 5: Deduplication & Insertion

10. **Cross-referenced research results against existing KB entries** to avoid duplicates. Skipped facts already covered (e.g., Pope Leo XIV's election, Maduro's capture, Assad regime fall).
11. **Inserted 21 new KB entries** using CTE-based SQL that atomically creates the entry and its source in one statement:
    ```sql
    WITH new_entry AS (
        INSERT INTO kb_entries (fact, related_claim, confidence_score,
            disinformation_categories, keywords, is_time_sensitive,
            valid_from, valid_until, created_by_model, status)
        VALUES (...) RETURNING id
    )
    INSERT INTO kb_entry_sources (kb_entry, url, source_name, source_type,
        relevant_excerpt, access_date)
    SELECT id, ..., CURRENT_DATE FROM new_entry;
    ```
12. **Deactivated 1 outdated entry** (Tulsi Gabbard "nomination pending" → replaced with confirmed entry).
13. **All entries tagged** with `created_by_model = 'claude-opus-4-6-downvote-review'` for traceability.

### Phase 6: Independent Verification (Parallel Subagents)

14. **Launched 3 parallel verification agents**, each assigned ~7 entries to fact-check against live web sources. Each agent independently searched for authoritative sources and checked every specific claim (dates, vote counts, names, percentages).

15. **Verification results:**
    - **12 entries fully verified** — no issues found
    - **9 entries flagged with concerns** — specific inaccuracies or imprecisions identified

### Phase 7: Corrections

16. **Applied 9 corrections** via `UPDATE` statements on `kb_entries.fact`:

| Entry | Issue Found | Correction Applied |
|-------|------------|-------------------|
| #4 Gulf of Mexico | "~Feb 10" date was imprecise | Changed to "February 18, 2025" (the formal GNIS update date) |
| #5 China tariffs | Conflated trade truce and Supreme Court ruling | Separated into two distinct events with specific details (Geneva agreement May 12, SCOTUS Feb 20, 2026) |
| #6 COVID microchip | "Smallest microchip too large for needle" was technically imprecise | Clarified that bare chips could fit but no functional tracking system (antenna + power) could |
| #9 NYC Mayor | Called Mamdani "a member of the Democratic Party" | Added "and the Democratic Socialists of America" |
| #12 NY adultery | Said "one of 17 states" | Corrected to "approximately 16 states" per Newsweek |
| #13 Muslim Brotherhood | Said designations began Nov 24, 2025 | Clarified EO was signed Nov 24 but actual designations came in January 2026; added FTO vs SDGT distinction per chapter |
| #14 Gold Card | Said Platinum Card "offers tax benefits" as if implemented | Added "has not been implemented and would require Congressional action"; clarified Gold Card as a "gift" not payment |
| #17 Israel vaccine | Used single-point figures (64%, 93%) | Changed to ranges (39-64% infection, 88-93% hospitalization) with time window context |
| #21 Minneapolis | "December 1" start date, "2,000-2,100" agents | Corrected to "December 1-3 (formally announced December 4)"; added "peak may have reached 4,000"; noted ~400 remaining through late Feb |

---

## Actions Taken

### 1. Snippet Hiding

| Metric | Count |
|--------|-------|
| Total downvoted snippets found | 135 |
| Already hidden (auto-hide trigger at 2 downvotes + manual) | 57 |
| **Newly hidden in this review** | **78** |
| Still visible after review | 0 |

### 2. Knowledge Base Entries Created

**21 new KB entries** across 13 topic areas. Each entry has:
- One verified external source (in `kb_entry_sources`)
- Spanish-language keywords for the pipeline's Spanish radio analysis
- A `related_claim` field written as explicit pipeline guidance

| # | Topic | Conf. | Source | Type |
|---|-------|-------|--------|------|
| 1 | South Korea martial law (Yoon, Dec 2024) | 95 | NPR | tier2_major_news |
| 2 | Assad fled Syria to Russia | 95 | NPR | tier2_major_news |
| 3 | Pope Leo XIV name honors Leo XIII | 90 | CNBC | tier2_major_news |
| 4 | Gulf of Mexico → Gulf of America (EO) | 95 | NPR | tier2_major_news |
| 5 | 145% tariffs on China (temporary, Apr 2025) | 95 | NPR | tier2_major_news |
| 6 | COVID vaccine microchip debunked | 99 | FactCheck.org | tier1_factchecker |
| 7 | Gene Hackman death (Feb 2025) | 99 | NPR | tier2_major_news |
| 8 | Hulk Hogan death (Jul 2025) | 99 | ESPN | tier2_major_news |
| 9 | NYC Mayor: Zohran Mamdani (ASR fix) | 99 | NYC.gov | official_source |
| 10 | Pam Bondi confirmed as AG | 99 | NPR | tier2_major_news |
| 11 | Tulsi Gabbard confirmed as DNI | 99 | DNI.gov | official_source |
| 12 | NY adultery decriminalized | 99 | NPR | tier2_major_news |
| 13 | Muslim Brotherhood chapters → FTO/SDGT | 95 | White House | official_source |
| 14 | Trump Gold Card visa program | 95 | CBS News | tier2_major_news |
| 15 | ICJ provisional measures on Gaza | 95 | ICJ.org | official_source |
| 16 | Russia annexed Crimea (2014) | 99 | Wikipedia | other |
| 17 | Israel COVID vaccine effectiveness | 95 | NPR | tier2_major_news |
| 18 | Delcy Rodríguez acting president | 95 | Al Jazeera | tier2_major_news |
| 19 | 2024 Venezuelan election (AP-verified) | 95 | PBS/AP | tier1_wire_service |
| 20 | Edmundo González exile in Spain | 95 | CBS News | tier2_major_news |
| 21 | Minneapolis Operation Metro Surge | 90 | CBS News | tier2_major_news |

**1 entry deactivated:** `131bc987` — Tulsi Gabbard "nomination pending" (superseded by entry #11).

### 3. Embedding Backfill Script

Created `src/scripts/backfill_kb_embeddings.py` — finds KB entries without embeddings, generates them via OpenAI `text-embedding-3-large`, and inserts into `kb_entry_embeddings`.

**To generate embeddings, run:**
```bash
cd /Users/j/GitHub/verdad
python -m src.scripts.backfill_kb_embeddings
```
Requires `SUPABASE_URL`, `SUPABASE_KEY`, and `OPENAI_API_KEY` env vars.

---

## Why This Matters

### Root Cause: Knowledge Base Staleness

The primary root cause across all 78 snippets was **KB staleness** — the AI pipeline flagged real events as disinformation because its KB didn't yet contain the relevant facts. When the pipeline encounters a claim like "Pope Leo XIV met with abuse victims," it searches the KB for context. If no entry exists for Pope Leo XIV, the pipeline may conclude the pope is fictional.

### Error Pattern Breakdown

| Error Type | Snippets | Example |
|-----------|----------|---------|
| Real person/entity flagged as fictional | 10 | Pope Leo XIV called "non-existent" |
| Real event flagged as fabricated | 25 | Maduro capture, Assad fall, martial law |
| Real policy flagged as false claim | 9 | Gulf renaming, Gold Card, tariffs |
| Real death flagged as false | 2 | Gene Hackman, Hulk Hogan |
| Real appointment flagged as false | 5 | Bondi as AG, Gabbard as DNI, Rubio as SoS |
| ASR error treated as fabrication | 3 | "Soran Nandani" = Zohran Mamdani |
| Nuanced topic oversimplified | 8 | Israel/Palestine, COVID vaccines |
| Correctly flagged but poor analysis | 16 | Various — analysis had factual errors |

### The ASR Problem

The "Soran Nandani" = "Zohran Mamdani" case reveals a systemic issue: the pipeline's speech recognition can distort unfamiliar names, and the analysis stage treats the distorted name as evidence of fabrication. The KB entry now includes both names so the pipeline can recognize this pattern.

---

## Database Changes Summary

### Tables Modified

```
user_hide_snippets:   +78 rows (hiding downvoted snippets)
kb_entries:           +21 rows (new facts), 1 UPDATE (deactivated), 9 UPDATEs (corrections)
kb_entry_sources:     +21 rows (one source per new entry)
kb_entry_embeddings:  pending +21 rows (via backfill script)
```

### How to Query the New Entries

```sql
-- All entries from this review
SELECT * FROM kb_entries WHERE created_by_model = 'claude-opus-4-6-downvote-review';

-- Entries needing embeddings
SELECT e.id, e.fact FROM kb_entries e
WHERE e.status = 'active'
AND NOT EXISTS (SELECT 1 FROM kb_entry_embeddings emb WHERE emb.kb_entry = e.id);

-- Verify sources exist for all new entries
SELECT e.id, e.fact, s.source_name, s.source_type, s.url
FROM kb_entries e
JOIN kb_entry_sources s ON s.kb_entry = e.id
WHERE e.created_by_model = 'claude-opus-4-6-downvote-review';
```

### KB Stats Before/After

| Metric | Before | After |
|--------|--------|-------|
| Active KB entries | 543 | 563 |
| Entries with embeddings | 543 | 543 (21 pending) |
| Deactivated entries | 5 | 6 |
| Superseded entries | 103 | 103 |
| Downvoted snippets visible | 78 | 0 |

---

## Recommendations

1. **Run the embedding backfill** to make the 21 new entries searchable via the RAG pipeline
2. **Consider a recurring monthly downvote review** to catch new false positives early
3. **Add ASR-aware fuzzy matching** for proper nouns — the Soran/Zohran case shows the pipeline needs name-similarity checks
4. **Review time-sensitive entries periodically** — entries with `is_time_sensitive = true` should be checked for expiration
5. **Consider lowering the auto-hide threshold** from 2 downvotes to 1, or at least flag single-downvote snippets for manual review

---

## Appendix: Entry IDs for Review

All entries can be queried by their UUIDs. The `created_by_model = 'claude-opus-4-6-downvote-review'` tag makes them easy to find, audit, or roll back if needed:

```sql
-- To roll back all changes if needed:
DELETE FROM kb_entry_sources WHERE kb_entry IN (
    SELECT id FROM kb_entries WHERE created_by_model = 'claude-opus-4-6-downvote-review'
);
DELETE FROM kb_entries WHERE created_by_model = 'claude-opus-4-6-downvote-review';

-- To re-activate the old Gabbard entry:
UPDATE kb_entries SET status = 'active', deactivation_reason = NULL
WHERE id = '131bc987-0f4e-4421-983a-5ace40ad82cd';
```
