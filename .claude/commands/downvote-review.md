# Downvote Review

Review downvoted snippets, hide them, create corrective KB entries, and generate a report.

## Steps

### 1. Find unreviewed downvoted snippets

Use the Supabase MCP to query for downvoted snippets that haven't been processed yet:

```sql
SELECT
    s.id AS snippet_id,
    s.title,
    s.explanation,
    s.disinformation_categories,
    s.confidence_scores,
    s.created_at,
    drq.status AS queue_status,
    COUNT(uls.id) FILTER (WHERE uls.value = -1) AS downvote_count
FROM snippets s
JOIN user_like_snippets uls ON uls.snippet = s.id
LEFT JOIN downvote_review_queue drq ON drq.snippet_id = s.id
WHERE uls.value = -1
AND (drq.status IS NULL OR drq.status = 'pending' OR drq.status = 'error')
AND NOT EXISTS (
    SELECT 1 FROM user_hide_snippets uhs WHERE uhs.snippet = s.id
)
GROUP BY s.id, drq.status
ORDER BY s.created_at DESC;
```

If no results, check for completed reviews too:
```sql
SELECT status, COUNT(*) FROM downvote_review_queue GROUP BY status;
```

Report findings to the user. If no unreviewed snippets exist, say so and stop.

### 2. Group by theme

Analyze the snippet titles and categories to group them into thematic clusters. Present the groups to the user for review.

### 3. Hide snippets

For any unhidden snippets, insert into user_hide_snippets:
```sql
INSERT INTO user_hide_snippets (snippet)
VALUES ('<snippet_id>')
ON CONFLICT (snippet) DO NOTHING;
```

Also insert into the review queue:
```sql
INSERT INTO downvote_review_queue (snippet_id, downvoted_at)
VALUES ('<snippet_id>', now())
ON CONFLICT (snippet_id) DO NOTHING;
```

### 4. Research and create KB entries

For each thematic group:
1. Use subagents to research the correct facts via web search
2. Find authoritative sources (Reuters, AP, NPR, official gov sites, fact-checkers)
3. Check existing KB entries to avoid duplicates:
   ```sql
   SELECT id, fact FROM kb_entries WHERE status = 'active' AND fact ILIKE '%<keyword>%';
   ```
4. Insert new KB entries with sources using CTEs:
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
5. Use `created_by_model = 'claude-downvote-review'` for traceability

### 5. Verify entries

Launch verification subagents to fact-check each new KB entry against live web sources. Fix any inaccuracies found.

### 6. Generate embeddings

Run the backfill script:
```bash
source .venv/bin/activate && python -m src.scripts.backfill_kb_embeddings
```

### 7. Update queue status

Mark all processed snippets as completed:
```sql
UPDATE downvote_review_queue
SET status = 'completed', processed_at = now(), kb_entries_created = <count>
WHERE snippet_id IN ('<id1>', '<id2>', ...);
```

### 8. Generate report

Create a markdown report at `reports/<date>_downvote_review.md` with:
- Executive summary (snippets found, hidden, KB entries created)
- Grouped snippet analysis
- KB entries created with sources
- Verification results and corrections
- Database changes summary

Commit and push the report.

### 9. Post to Slack

Post a summary to #verdad channel (ID: C07JYU3729G) using the Slack MCP tools, linking to the GitHub report.

## Notes

- The VERDAD Supabase project ID is `dzujjhzgzguciwryzwlx`
- Valid source_type values: tier1_wire_service, tier1_factchecker, tier2_major_news, tier3_regional_news, official_source, other
- KB entries need confidence >= 70 and at least one external source
- Include Spanish-language keywords since the pipeline analyzes Spanish radio
- Always check existing KB entries before creating new ones to avoid duplicates
