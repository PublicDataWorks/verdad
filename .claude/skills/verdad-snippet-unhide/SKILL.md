---
name: verdad-snippet-unhide
description: Investigate why a VERDAD snippet is hidden from verdad.app, verify and correct its analysis against primary sources, then unhide it and reconcile sibling clips of the same broadcast. Use whenever a snippet is missing from the feed or returns an empty page, when someone asks why a clip "disappeared" or cannot be found, when a downvote or dislike needs acting on, when an analysis is wrong and the clip must be pulled or restored, or when a journalist or partner reports that a clip they were sent no longer loads. Triggers on phrases like "why is this snippet hidden", "unhide this clip", "the analysis is wrong", "restore this snippet", "fix the analysis and republish", "this link is empty", "a reader downvoted this", or any request naming a snippet UUID plus visibility or accuracy. Covers the hide mechanism, the correction transaction with snapshot and rollback, cross-snippet consistency for rebroadcasts, and mojibake repair.
---

# VERDAD snippet unhide and analysis correction

Restoring a hidden clip is **never** just deleting a hide row. A clip is almost always hidden because
someone objected to the *analysis*, so unhiding it without fixing the analysis re-publishes the thing
that was objected to. Fix first, then unhide, then make the sibling clips agree.

## Critical configuration

- **Supabase project ID**: `dzujjhzgzguciwryzwlx` — use for every `execute_sql` call
- **Public clip URL**: `https://verdad.app/snippet/<snippet-uuid>`
- The only DB access layer in code is `src/processing_pipeline/supabase_utils.py` (`SupabaseClient`)

## Safety rules that govern this whole skill

From `CLAUDE.md` and `AGENTS.md`, and they are not optional:

- This environment talks to **production**. Be read-mostly by default.
- **Confirm with a human before any `UPDATE` or `DELETE` on production data.** Every write step below
  is something you propose as reviewable SQL and run only once a person says yes.
- Never run the prompt importer, a migration, or a deploy as part of this work.
- Do not commit the Supabase URL or keys anywhere new.

Write the whole correction as **one transaction** in a scratchpad `.sql` file, show it to the human,
and run it only on approval. Never hand-edit rows one statement at a time.

## Step 1 — Establish why it is hidden, before touching anything

Three different things make a clip invisible, and they have different fixes. Determine which.

```sql
select s.id::text,
       s.status,
       (s.confidence_scores->>'overall')::int              as overall,
       (select count(*) from user_hide_snippets h
         where h.snippet = s.id)                           as hide_rows,
       (select count(*) from user_hide_snippets h
         where h.snippet = s.id and h."user" is null)       as app_wide_hides,
       (select count(*) from user_like_snippets l
         where l.snippet = s.id and l.value = -1)          as dislikes,
       q.status                                            as queue_status,
       to_char(q.downvoted_at,'YYYY-MM-DD HH24:MI')        as downvoted_at,
       s.reviewed_by, s.reviewed_at
from snippets s
left join downvote_review_queue q on q.snippet_id = s.id
where s.id = '<uuid>';
```

Read the result against the three causes:

| Symptom | Cause | Fix |
|---|---|---|
| `hide_rows > 0` | a hide row exists | this skill |
| `overall < 95` | below the feed's confidence gate | not hidden; it is unranked. Only the analysis can change it |
| `status <> 'Processed'` | never finished the pipeline | a requeue, not an unhide |

**Then check the quarantine log, because that is where most hides came from.** A
dislike is the memorable cause, not the common one. The 2026-09 cleanup batches
account for the bulk of NULL-user hides:

```sql
select batch, previous_status, reason,
       to_char(quarantined_at,'YYYY-MM-DD HH24:MI') as quarantined_at,
       restored_at
from snippet_quarantine_log where snippet = '<uuid>';
```

`restored_at IS NULL` here is live state, not history. `reprocess_snippets.py
--quarantine-batch` selects exactly `batch IN (...) AND restored_at IS NULL`, so a
row left NULL means the snippet is still queued for re-analysis. Unhide it without
stamping `restored_at` and a later batch re-run silently overwrites your
correction. Step 3 stamps it.

**The gate, read from the live functions.** `get_snippets` (the feed) requires
`s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95` and left-joins
`user_hide_snippets`. `get_snippet` and `get_public_snippet` (the direct link) require only
`status = 'Processed'`, and check hiding with:

```sql
SELECT EXISTS (SELECT 1 FROM user_hide_snippets uhs WHERE uhs.snippet = snippet_id) INTO is_hidden;
```

That `EXISTS` **is not scoped to the calling user**. So one hide row hides the clip from every
non-admin viewer, including through its direct URL. A clip can pass the feed gate and still return an
empty record to a journalist holding the link.

### Where the hide row came from

Two sources, and they need different handling. Check the quarantine log first, because it is the
larger one by orders of magnitude.

**A cleanup batch.** `snippet_quarantine_log` holds the 2026-09 bulk hides. As of 2026-09-30 that is
24,306 rows across five batches, about 20,800 still unrestored, the largest being
`hide-2026-09-15-heuristics` at 17,855. A hide from here is not a reader objecting; it is a sweep. The
log row is also live state feeding `reprocess_snippets.py`, so clearing it is part of the unhide.

**A dislike.** Covered below. Memorable, and much rarer.

### How a dislike creates a hide row

Two triggers on `user_like_snippets` both write `user_hide_snippets (snippet)` with a **NULL user**:

- `on_downvote_queue_review` — fires on **any single** `value = -1`. It inserts the hide row *and* a
  `downvote_review_queue` row. One person's one dislike hides the clip app-wide.
- `update_snippet_hidden_status` — fires when the dislike count reaches **exactly 2**.

Because the first fires on a single dislike, most hides are one-click, not consensus. Confirm who and
when:

```sql
select l."user"::text, l.value, to_char(l.created_at,'YYYY-MM-DD HH24:MI:SS') as at
from user_like_snippets l where l.snippet = '<uuid>' order by l.created_at;
```

**The review queue is not being drained.** Check before promising anyone a review will happen:

```sql
select status, count(*), to_char(min(downvoted_at),'YYYY-MM-DD') as oldest
from downvote_review_queue group by status;
```

As of 2026-09-30 this read 154 `pending` with the oldest from 2026-03-19, and a single `completed`
row. Nothing processes the queue automatically. Say so plainly rather than implying a review is
pending. For scale: 21,507 hide rows exist, 21,028 of them NULL-user.

## Step 2 — Decide whether the objection was about the clip or the analysis

This is the judgement call the rest depends on. Read the analysis as the person who disliked it would
have:

```sql
select c.ord, (c.claim->>'score')::int as score,
       left(c.claim->>'quote',120)     as quote,
       c.claim->>'evidence'            as evidence
from snippets s
cross join lateral jsonb_array_elements(s.confidence_scores->'analysis'->'claims')
     with ordinality as c(claim, ord)
where s.id = '<uuid>' order by c.ord;
```

Then ask of every claim: **is there a retrieved source behind this, or is the model asserting from
memory?** The failure mode that produces most dislikes is a verdict of *fabricated* resting on
nothing retrieved, sometimes citing a fact-check that does not exist. Signals:

- evidence naming an outlet or URL that is not in the research findings
- `stage_4_tool_record` showing zero web searches
- `stage_4_citation_check.web_research_unobserved` non-empty with `applied: false`
- a genuine quotation scored as invented because the frame around it is false

If the analysis is defensible, the clip may genuinely warrant staying hidden. Say so and stop. If the
analysis is wrong, the hide is a symptom and correcting the analysis is the actual work.

### Where the fields actually live

Learn this before writing SQL, because the obvious guesses are wrong:

- `user_hide_snippets` keys on **`snippet`**, not `snippet_id`. `downvote_review_queue` keys on
  **`snippet_id`**. They differ.
- `confidence_scores` holds `overall`, `verification_status`, `categories`, `analysis`.
- `confidence_scores.analysis` holds `claims`, `score_adjustments`, `validation_checklist`.
- **Categories live in two places.** The `disinformation_categories` array column *and*
  `confidence_scores.categories`, a jsonb array copy. Correct both or the restored row carries
  contradictory verdict data — and if you are dropping a fabrication-asserting category because the
  verdict rests on nothing retrieved, leaving the copy behind defeats the point. Verify they agree
  afterwards.
- `score_adjustments` goes stale silently. When the claims change, `adjustment_reason` still describes
  the old verdict. Refresh it in the same `UPDATE`.
- `confidence_scores.analysis.explanation` is **empty** on production rows. The prose lives in the
  top-level `explanation` jsonb, as `explanation->>'english'` and `->>'spanish'`. Edit that one.
- `claims[]` items are `{quote, evidence, score}` with no status field. Per
  `prompts/stage_4/output_schema.json`, `quote` is "Direct quote of the false or misleading claim"
  and `evidence` is "Evidence demonstrating why the claim is false". `claims[]` is for the **false**
  claims only.

### What the active prompt now requires

Stage 4 reviewer **1.3.0** went live 2026-09-22 (VER-391). Match a hand correction to it:

- `claims[]` lists **only** claims a retrieved source contradicts, each opening its `evidence` with
  that source.
- A claim that was searched with no coverage, or never searched, gets **no `claims[]` entry**. Name it
  in `explanation` and in `score_adjustments.adjustment_reason`.
- The central claim is first in `claims[]` **only** when a retrieved source contradicts it.
- `overall` is never an average of `claims[].score`.
- Cases (ii) and (iii) must also drop any category whose name asserts fabrication, such as
  *Fabricated Content*, because the evidence gate reads a category name as a falsity verdict.
- Score ceiling 40 for an unsupported verdict is a **ceiling, not a target**.

Beware one gap: a sub-claim affirmatively verified as **genuine** has no structured home under 1.3.0.
It cannot sit in `claims[]` (nothing contradicts it) and it is not untested. Put it in the
`explanation` prose and say plainly that the element is real.

## Step 3 — Write the correction as one reviewable transaction

Use `templates/correct_and_unhide.sql` as the starting point. The shape, in order:

1. **Snapshot first.** Insert the current row into `snippet_analysis_snapshot` under a `batch` label
   like `manual-<YYYY-MM-DD>-<short-uuid>`. It carries `status`, `title`, `summary`, `explanation`,
   `disinformation_categories`, `confidence_scores`, `grounding_metadata`, `thought_summaries`,
   `analyzed_by`, `reviewed_by`, `reviewed_at`, `stage_3_prompt_version_id`. It is your rollback.
   **Omit `labels`.** It is `NOT NULL DEFAULT '[]'::jsonb`, and an explicit `NULL` violates the
   constraint rather than falling back to the default, so passing `null` aborts the whole
   transaction. Omitting it takes the default. The consequence to know: label associations are not
   captured, so if a correction also changes labels, snapshot those separately.
2. **Assert the snapshot landed, and that the snippet really was hidden.** Both, before any write.
   Note that `psql` does not interpolate `:'var'` inside a dollar-quoted body, so a `DO $$ ... $$`
   guard receives the literal token and fails to parse. Publish the values with `set_config(...,
   true)` inside the transaction and read them with `current_setting()` in the guard.
3. **Rewrite the analysis.** Correct claims, evidence, scores, `verification_status`, `overall`, the
   `explanation` prose, **both** category fields, and `score_adjustments`. Annotate each hand-touched
   claim so it is auditable, for example opening the evidence with `CORRECTED <date> (manual review):`
   or `GENUINE (manual review).`
4. **Stamp provenance.** Set `reviewed_by` to a marker such as `manual-consistency-pass-<YYYY-MM-DD>`
   and `reviewed_at = now()`. Never leave a hand edit wearing a model's name.
5. **Delete the hide row**, scoped to the one snippet.
6. **Stamp `restored_at` on any `snippet_quarantine_log` row still `NULL`**, or a later
   `--quarantine-batch` re-run overwrites the correction. Touch only the NULL ones, so a row an
   earlier restore already stamped keeps its timestamp and the rollback can tell yours apart.
7. **Close the queue row**: `status = 'completed'`, `processed_at = now()`.
8. **Delete the `snippet_embeddings` row** so Stage 5 re-embeds. The vector was built from the old
   explanation, so leaving it makes the clip retrievable by its withdrawn wording and not by its
   corrected wording.
9. **Record the verdict** in `snippet_hide_review` (`snippet`, `batch`, `verdict`, `why`,
   `reviewed_at`) so the reason survives. That table is `PRIMARY KEY (snippet, batch)`, so **upsert**:
   `on conflict (snippet, batch) do update`. A plain insert is what lets the rollback flip the same
   row to `reverted` instead of aborting on the key.

**The rollback must restore visibility, not just the analysis.** Restoring the snapshot alone leaves
the hide row deleted and the queue `completed`, so the analysis you just rejected becomes publicly
readable — the hide row was the only thing keeping it out of `get_snippet` and `get_public_snippet`.
A correct revert also re-inserts the NULL-user hide row, puts `restored_at` back to `NULL` on the
quarantine rows this run stamped, sets the queue back to `pending`, drops the embedding again, and
flips the verdict row to `reverted`. This is why step 2 asserts the snippet was hidden: it makes
re-inserting one hide row a faithful restoration rather than a guess.

Key the quarantine revert on the snapshot's `snapshot_at` with **exact equality**, never `>=`. Because
`now()` is `transaction_timestamp()`, the snapshot and the forward quarantine stamp are the identical
value, so equality matches precisely the rows this run touched. A `>=` would also catch any row a
*later* restoration stamped after this correction committed, and clearing that would hand an unrelated
snippet back to quarantine reprocessing.

**Write the file so it runs through either path.** Avoid psql meta-commands entirely: `\set` and
`:'var'` work in `psql` but fail on line 1 through the Supabase MCP `execute_sql` tool, which is how
most of this work actually gets run. Publish the snippet id and batch once with
`set_config(..., true)` and read them back with `current_setting()` everywhere else. Send the file as
one unit either way, since transaction-local settings do not survive being run statement by statement
— and neither does the atomicity the template exists for.

Guardrails while writing it:

- Wrap in `begin; ... commit;` and keep every statement keyed to the explicit UUID. No set-based
  `UPDATE` that could touch neighbours.
- Beware SQL precedence on JSON: `'x' || to_jsonb(l)->>'k'` parses as `('x' || to_jsonb(l))->>'k'`.
  Parenthesise: `'x' || (to_jsonb(l)->>'k')`.
- Queries against the whole `snippets` table time out at 60s. Narrow by date range rather than
  retrying.

### Verify after committing

```sql
select (select count(*) from user_hide_snippets where snippet = '<uuid>')      as hide_rows,
       (select status from downvote_review_queue where snippet_id = '<uuid>')  as queue_status,
       (confidence_scores->>'overall')::int                                    as overall,
       reviewed_by, to_char(reviewed_at,'YYYY-MM-DD HH24:MI')                   as reviewed_at
from snippets where id = '<uuid>';
```

`hide_rows` must be 0, `overall` at or above 95 for the feed, and `reviewed_by` your marker. Then open
the public URL and confirm it renders.

## Step 4 — Reconcile sibling clips of the same broadcast

Correcting one clip in isolation creates a worse problem: two clips of the same programme giving
different verdicts on the same sentence. Radio stations rebroadcast, and VERDAD clips each airing
separately, so the same script commonly exists several times.

Find the siblings by content, not by time:

```sql
select s.id::text, to_char(s.recorded_at,'YYYY-MM-DD HH24:MI') as recorded_at,
       s.radio_station_code, (s.confidence_scores->>'overall')::int as overall,
       left(coalesce(s.title->>'english',''),70) as title_en
from snippets s
where (s.transcription ilike '%<distinctive phrase>%'
    or s.translation   ilike '%<distinctive phrase>%')
order by s.recorded_at;
```

Then compare claim by claim across them and make every recurring claim agree on score, on verdict,
and on the source cited. Where they disagree, the disagreement itself is the bug. A worked example:
two airings 48 days apart initially differed on one score; after correction all four recurring claims
matched, and the fact that the host claimed a Supreme Court ruling "today" on two dates seven weeks
apart became the strongest finding in the write-up.

Apply the same batch label and the same `reviewed_by` marker to every sibling you touch, so the pass
is one auditable unit.

### Mojibake repair, while you are in there

Accented characters are corrupted on some rows, for example `Nicolás` stored as `Nicol\b00e1s`,
through the Spanish text and the category labels. Detect and repair in the same transaction:

```sql
select left(id::text,8) as sid
from snippets
where recorded_at >= '<date>'
  and (confidence_scores::text ~ '\\\\b00[0-9a-f]{2}' or explanation::text ~ '\\\\b00[0-9a-f]{2}');
```

Also re-attribute anything the analysis stated as our finding when it is the host's phrasing. Calling
someone "former President" in our own summary, when that is the broadcaster's word, is our error.

## Step 5 — Update anything already sent outside

If a briefing, email or artifact cited the clip while it was hidden, it is now wrong. Before sending
or re-sending:

- Re-read the live page and confirm what it says now.
- Correct any claim in the write-up about hidden or restored state, and about what the analysis says.
- State the evidence basis honestly. Count it **per claim**, not per clip, because one clip commonly
  mixes bases: a named checkable source, a search that returned nothing, and a bare assertion are
  three different things and readers deserve to know which backs each verdict.
- Never let a transparency claim outrun the data. A line saying "the card says so whenever a verdict
  rests on general knowledge" must be checked against the rows before it ships.

Hold any outbound email until the artifact or document is updated, so the two do not contradict each
other on whether the clip is visible.

## Known open defects to mention, not to fix here

- `on_downvote_queue_review` turns one dislike into an app-wide hide. Product-level fix, out of scope.
- The `downvote_review_queue` has no processor.
- `get_snippet` and `get_public_snippet` do not scope the hide check to the viewer.

Name these when they are the cause. Do not change a trigger or a read function as part of an unhide.
