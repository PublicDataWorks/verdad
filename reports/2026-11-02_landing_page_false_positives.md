# Landing page false positives (VER-445), 2026-11-02

## What visitors saw

`get_landing_page_content()` feeds the carousel on the logged-out landing page. It took any snippet a user had ever
starred, sorted by confidence, and checked nothing else. Of the 10 cards it served on 2026-11-02:

| snippet | card | problem |
|---|---|---|
| `36a7de99` | False Report on the Capture of Nicolás Maduro | true event; already hidden from the feed |
| `fa658d31` | False News: Delcy Rodríguez Interim President | true event; already hidden |
| `7c476c2b` | Speaker Exaggerates ... Assassination of Maduro | judged 2026-03, before reviewer 1.3.0 |
| `de8e8301` | False Declaration of Electoral Victory in Honduras for Nasry Asfura | Asfura won in 2025; the verdict cites 2021 results |
| `de1984fb` | Fictional News Report on Papal Appointment | says Pope Leo XIV does not exist; hidden, 2 dislikes |
| `3a7e9f55` | False Claim of Venezuelan Election Victory | treats the CNE result as fact; hidden, 2 dislikes |
| `d4917b39` | The "Latinx" Debacle | status Error; its own explanation says it is not disinformation |
| `8ad70a84`, `5b55bdfc`, `234548a5` | 2020 election, Ukraine aid, veteran murder | 2024 to early 2026 verdicts, never re-reviewed |

## Why

1. **No filter on the carousel.** It ignored `user_hide_snippets`, status, dislikes and verdict age.
2. **Stale verdicts.** Most of the wrong Maduro verdicts were written from January to September 2026, while
   pipeline-written KB entries called the capture a "viral hoax" (53 entries, deactivated in cleanup 12 and VER-413)
   and SearXNG was mostly down (VER-390). The 2026-09-24 stale-verdict runbook was never run, so the verdicts stayed.
3. **The pipeline handles this fact correctly now.** Stage 3 1.5.0 verdicts from October cite the capture as real, and
   the only active KB entry on Maduro is the analyst seed `e9427617`. No prompt change is needed for this fact.
4. **Re-review is blocked.** Gemini quota has been exhausted since 2026-10-24 (VER-438, VER-441). No Stage 4 review
   has run since 2026-10-23, and 24k audio files are in Error with a 429.

## What changed (applied to production 2026-11-02)

- Migration `20261102233630_landing_page_safe_snippets`. A carousel snippet now needs status Processed, no hide,
  no dislikes, confidence 95 or higher, a review on or after 2026-09-22 04:07:30 UTC (reviewer 1.3.0), a recording
  date in the last 180 days and no Fabricated Content category. Each snippet appears once, sorted by star count and
  then recency. New table `landing_page_snippet_overrides` (`pin` / `block`) lets staff curate the carousel by SQL:
  `INSERT INTO landing_page_snippet_overrides (snippet, mode, note) VALUES ('<id>', 'block', 'why')
  ON CONFLICT (snippet) DO UPDATE SET mode = EXCLUDED.mode, note = EXCLUDED.note;`
  A `pin` skips the star, confidence, review-date, recency and Fabricated Content checks; status, hide and dislike
  checks still apply, so only pin a snippet someone has checked.
  The result shape is unchanged. The new set of 10 was checked as `anon`.
- Quarantine batch `hide-2026-11-02-maduro`
  (`supabase/database/sql/cleanup_2026_11/01_hide_maduro_capture_denials.sql`): 49 visible verdicts that deny the
  capture (or the New York imprisonment, or the 32 Cuban deaths) plus `de8e8301`, hidden through NULL-user rows in
  `user_hide_snippets`. Logged and reversible.

## Still to do (needs Gemini quota)

1. Requeue the batch for Stage 4 and restore any snippet whose new verdict is correct:
   `python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-11-02-maduro --stage 4 --execute`
2. Re-review only, not hidden: these verdicts accept the capture but dispute timing, the "kidnapping" framing or a
   detail. Some are probably wrong too, for example `fa2fe5c3` on the reported use of Claude in the
   raid (`9e4c9eff` makes the same Claude point but also denies the capture, so it is in the hidden batch). Use
   `--ids-file`:
- `fbe19f67-ae33-4233-bd7c-0ca2771b8a71`
- `1562add7-289a-4d7b-a9c2-54d042ccd858`
- `45abe6ff-71ba-4c24-8a83-e51caa1a0427`
- `1ec4d69d-833f-46cf-9ce2-9605716d4d5b`
- `03a43bf2-92a8-47eb-8748-596fda5687e0`
- `4303428f-0e2e-4d90-af82-b6df2dc911e0`
- `31ac6435-d1e4-4793-a4c3-f9126ef9521a`
- `3ced6014-dd53-4164-bbff-bf636e1c48e6`
- `237c623d-de9b-4855-a120-32b1eb96eb8e`
- `b77e8504-6433-4a54-b2e2-fa7f54aa1f98`
- `05b1c3f5-2c03-4db5-b059-4c068b7e88fe`
- `fa2fe5c3-6fd8-4e2c-854c-3c43a36e6a34`
- `2cb4496b-40a6-429b-8a46-96209c8e7747`
- `e6dfc1fc-a439-4924-aa13-a24cbca1a786`
- `ea1da761-f58a-414a-9989-3556eee9589d`
- `379fdabf-263d-48c6-a41d-ee6a998b4c81`
3. Run the 2026-09-24 stale-verdict sweep (1,722 snippets judged before reviewer 1.3.0).
