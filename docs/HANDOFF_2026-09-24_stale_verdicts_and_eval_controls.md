# Handoff: stale verdicts, KB currency, and eval controls that reward the failure (2026-09-24)

Written by Claude (Cowork session for Rajiv Sinclair) after an end-to-end test of a weekly monitoring-brief
routine over snippets recorded 2026-09-16 to 22. Every claim in the brief was re-verified by blind web research,
so the run doubled as an audit of VERDAD's own labels. This file records what the audit found and what the PR
that adds it changes.

## What the audit found

1. **High-confidence "false" labels on true events.** Five visible or recently written verdicts, all verified
   against tier-1 sources:

   | snippet | label | what is true |
   |---|---|---|
   | `68ad3d0d` Radio Libre 790 | 98, "Fabricates Supreme Court Ruling" | *USPS v. California*, No. 26A305, stay denied 2026-09-14 (Alito, Thomas dissenting) |
   | `95b46c92` KWST (Vatican News) | 100, "Fabricated News Report" | Leo XIV turned 71 on Monday 2026-09-14; 9/11 remarks at the 2026-09-13 Angelus |
   | `ef2070d3` Radio Libre 790 | 90, "False Claim of Maduro's Capture" | Maduro was captured in Caracas on 2026-01-03 |
   | `50a1cea7` La Poderosa | 95, Kirk reference flagged false | Kirk was killed 2025-09-10 |
   | `ba7c2118` US Arab Radio | 95, sanctions relief flagged false | Comprehensive sanctions ended; Caesar Act repealed in the FY2026 NDAA |

2. **Most of these came from before the recent fixes, and nothing re-checks them.** Four of the five were
   analysed under Stage 3 1.3.0/1.4.0 or reviewed before reviewer 1.3.0 went live (2026-09-22 04:07 UTC); the
   fifth (`ef2070d3`) was scored by gemini-2.5-flash below the Stage 4 threshold and never reviewed. As of
   2026-09-24, **1,722 visible (not user-hidden) snippets recorded since 2026-08-01 carry verified_false at 95+
   and were last judged before reviewer 1.3.0**; 69 were judged after it. A prompt fix changes new verdicts only.

3. **The KB poisoned later verdicts.** `ba7c2118`'s review cited two pipeline-written KB entries:
   - `ac499d1a` "Marco Rubio is a U.S. Senator for Florida", `is_time_sensitive = true`, `valid_until = 2029-01-03`,
     sourced to a 2022 Senate biography page, written 2026-09-16.
   - `0015ac69` "As of August 2026 ... the Caesar Act remained in effect", sourced to a Reuters URL with an
     excerpt that contradicts the actual state of the law (the article could not be retrieved; treat it as
     likely invented).
   Both are now deactivated. The observed-URL gate (VER-391, 2026-09-21) blocks the second pattern going forward.
   Nothing blocked the first: the URL was real, just two years stale for a fact stated as current.
   59 active pipeline entries today are time-sensitive, stated as current, and cite a source more than 180 days
   older than the entry.

4. **The Stage 4 eval set scored true reports as controls.** `prompts/eval/stage_4/stage-4-post-cutoff-reviewer-2026-09.json`
   listed 12 controls ("fabrication with a retrieved contradicting source ... detections the rule must not
   weaken"). Six are accurate reports: `95b46c92` (Pope's birthday), `50a1cea7` (Kirk), `1ecb1b30` (Messi's
   Oct 6 farewell vs Benin, announced 2026-09-16), `cc377301` (Kennedy Center closure and Patel's 2026-09-15
   Senate testimony, both AP/CBS-confirmed), `0c91142e` (al-Sharaa decrees and the al-Abdullah arrest, real May
   2026 news rebroadcast in September), `eb72097b` (Syria's SST rescission took effect 2026-08-24). A reviewer
   that stopped calling these false would have shown up as "true positives lost". Kept as controls after
   checking: `09200a34` (dinosaurs), `464e0dd9` (Albicans Cure), `f5cb1009` (wrong election date). Not re-checked:
   `e901055b`, `38a9d35b`, `c9b90151`.

## What the PR changes

- **Eval sets.** The six true reports move from control to reported. Added reported `68ad3d0d`, `ba7c2118`
  (Stage 4 set) and `ef2070d3` (Stage 3 post-cutoff set). Added controls `6080bea6` (no Supreme Court I-220A
  ruling exists) and `841a9110` (wrong date for Florida's citizenship marker; invented 30-year sentence).
- **KB currency gate** (`validate_kb_currency` in `stage_4/tools.py`). A time-sensitive fact recorded as still
  true (no `valid_until`, or one in the future) must cite a source published within
  `KB_CURRENT_FACT_MAX_SOURCE_AGE_DAYS` (180). History (a closed validity window) may cite old sources. The
  Rubio entry would have been rejected.
- **kb_updater 1.1.0.** Same rule in the prompt, no projected `valid_until`, excerpts copied from tool output,
  no denial entries unless a retrieved source states the denial.
- **Stale-verdict requeue** (`src/scripts/reprocess_snippets.py`):
  - `--stale-verdict TIMESTAMP`: Processed verified_false snippets whose last verdict (`reviewed_at`, else
    `created_at`) predates TIMESTAMP.
  - `--deactivated-kb`: snippets whose review wrote a KB entry that is now deactivated.

  With the runbook filters below, `--stale-verdict` selects 1,722 snippets and `--deactivated-kb` 909 (visible, 95+,
  counted by SQL on 2026-09-24; the sets overlap).

## Runbook (not run; needs a human go-ahead, it spends Gemini quota)

```bash
# dry run: counts and SQL only
python src/scripts/reprocess_snippets.py --stale-verdict 2026-09-22T04:07:30Z --since 2026-08-01 \
    --min-confidence 95 --not-hidden --stage 4
# then in batches sized to the Gemini quota, newest first
python src/scripts/reprocess_snippets.py --stale-verdict 2026-09-22T04:07:30Z --since 2026-08-01 \
    --min-confidence 95 --not-hidden --stage 4 --limit 100 --execute
python src/scripts/reprocess_snippets.py --deactivated-kb --min-confidence 95 --stage 4 --limit 100
```

Stage 4 re-runs the web researcher, so a re-review is a fresh check, not a re-read of the frozen Stage 3 evidence.
Measure a first batch of 100 before the rest: how many drop below 95, and spot-check 10 of those and 10 that stay.

## Follow-ups not in this PR

1. **Record KB retrievals.** `kb_entry_snippet_usage` only logs `triggered_creation` / `triggered_update`, so when
   an entry is deactivated there is no list of the verdicts that *read* it. Log a `retrieved` row from the KB
   search tools (Stage 1 and Stage 4) and make deactivation requeue those snippets.
2. **Schedule the stale sweep.** After each reviewer or Stage 3 prompt activation, requeue visible verdicts
   judged under the previous version, rate-limited. Needs plan mode (flow topology).
3. **Excerpt check.** Verify `source_excerpt` against the text the search/read tool actually returned, the same
   way URLs are checked against `observed_urls`.
4. **Audit the Stage 3 eval controls.** The post-cutoff set's controls reuse the fabricated-content set; given
   finding 4, re-verify them with web search before the next Stage 3 prompt evaluation.
5. **Below-threshold verdicts.** `ef2070d3` (flash, 90, never reviewed) shows wrong labels also live below 95.
   They are not in the feed, but the weekly brief and search both read them.
