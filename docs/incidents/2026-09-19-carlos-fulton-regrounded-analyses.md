# Regrounded analyses for the three Fulton County clips (2026-09-19)

**Status:** applied to production
**Rows:** `fb43bf56`, `c253e70f`, `3e53d8e1` (all WNMA 1210 AM, Miami; 10 Sep 2026 07:24–07:27 UTC, one segment)
**Batches:** `unmask-2026-09-19-carlos` (score restore, by fredericton-ce), `regrounded-2026-09-19-carlos` (this work)
**Related:** VER-373, VER-388, VER-389, VER-358, VER-369, PR #120

## Why this happened

Carlos Chirinos (palabra/NAHJ) reported that Fulton County material did not appear in his
verdad.app search. The three clips above were invisible because the Stage 3/4 **evidence gate**
(`apply_evidence_caps`, `EVIDENCE_CAP_MAX_SCORE = 40`) had clamped their confidence to 40, and
`public.get_snippets` only returns rows with `status = 'Processed' AND (confidence_scores->>'overall')::int >= 95`.
Nothing was "hidden": `user_hide_snippets` is a separate, per-user mechanism and none of these rows were in it.

These three are the **complete** set of gate-capped Fulton County election clips. An earlier
count of "93 Fulton/Georgia rows" was a false positive: it matched `transcription ILIKE '%georgia%'`,
and 86 of those are WLEL 94.3 FM, a Georgia station whose transcripts say "Georgia" constantly.
Restricted to `%fulton%`, the Stage 3-capped set is four rows, two of which are Fulton **Bank**
sponsor mentions. (Census by kathmandu-98.)

fredericton-ce restored the three scores to 95 at 20:05 UTC. This document covers what came after:
a full regrounding of the analysis text, which turned up two real accuracy defects.

## What was wrong with the analyses

### 1. Fabricated citations (3e53d8e1) — the serious one

The Stage 4 `web_research` narrative cited, with URLs, publication dates and verbatim
"Relevant Excerpt" quotations:

- `politifact.com/factchecks/2026/09/12/radio-mundo/fabricated-quote-justice-alito-election-day/`
- `factcheck.org/2026/09/13/meme-invents-alito-quote-on-election-day/`
- `apnews.com/article/fact-checking-california-vote-count-timeline-2024-1a2b3c4d5e`

None exist. The clip's own `stage_3_verification_evidence` logs **6 searches, all `no_results`**,
including a targeted `site:politifact.com` query. The AP slug `1a2b3c4d5e` also appears on an
unrelated snippet (`34b9799d`, Iran drone) — the same placeholder identifier on a different topic,
which is what confirmed fabrication rather than retrieval failure.

This was **not a one-off**. Of the 8 Stage 4-capped rows originally scoring 95+, 5 cite specific
URLs with quoted excerpts against Stage 3 logs containing no contradicting results; `da72ac15`
produced 15 sourced citations with 10 excerpts on top of a Stage 3 log with zero searches.
Stage 3-capped rows carry no `web_research` key at all (0/20 sampled), so this is Stage 4-only.

### 2. A true claim labelled false (3e53d8e1) — the one that would have burned a reporter

The analysis said the host's Alito quotation was fabricated, scored that claim **100 for falsity**,
and cited the two invented fact-checks as proof.

**The quotation is genuine.** At oral argument in *Watson v. Republican National Committee* on
2026-03-23, Justice Alito said: "…Labor Day, Memorial Day, George Washington's birthday,
Independence Day, birthday and Election Day, and they're all particular days." The host's Spanish
paraphrase is fair. Verified against contemporaneous reporting and the Court's own opinion.

The clip is still disinformation, and now on a *verifiable* basis: there was no 2026-09-10 ruling,
and the Court had already decided the question the opposite way on 2026-06-29 in *Watson*
(No. 24-1260, 5-4, Barrett writing), upholding Mississippi's counting of ballots postmarked by
election day and received up to five business days later. The host presents an oral-argument remark
from a case his side **lost** as a ruling handed down "today".

### 3. Unsupported corroboration claims (all three)

Rendered explanations asserted verification that never happened:

- `3e53d8e1`: "as confirmed by multiple fact-checkers" — nothing was retrieved.
- `fb43bf56`: "Government agencies, courts, and fact-checkers have repeatedly refuted these claims" —
  7 searches ran, all returned nothing; the Stage 3 summary itself rests the verdict on
  "extensive public knowledge predating the current date", i.e. model prior knowledge, not evidence.
- `c253e70f`: implied audits, investigations and news reports had been checked. 4 searches ran;
  3 returned nothing and the 4th returned one genuine source — the 2020 DOJ narco-terrorism
  indictment of Maduro, which supports only the kernel the host builds on.

A correction to an earlier read of my own: these last two rows *do* have search logs. They store them
at the top level of `grounding_metadata` under `searches_performed` / `verification_summary`; only
`3e53d8e1` nests them under `stage_3_verification_evidence`. The null in that field is the extracted-evidence
block, not the search log. A draft that said "no searches were run" was caught before it shipped.

## What was changed

1. **Snapshot** of all three rows (post-restore state) into `snippet_analysis_snapshot`,
   batch `regrounded-2026-09-19-carlos`, at 20:08:31 UTC — before any write.
2. **`explanation.english` / `explanation.spanish` rewritten** on all three rows. Each carries an
   editor's note naming the specific error corrected, then an analysis grounded only in the
   transcript, the clip's own search log, and (for 3e53d8e1) hand-verified primary sources.
   Constraints enforced and linted: no URLs in rendered text; no assertion that any outlet, court,
   agency or fact-checker confirmed/refuted/debunked anything that was not actually retrieved;
   every closing line states honestly what the automated verification did and did not find.
3. **`confidence_scores` corrected on 3e53d8e1**: the Alito claim re-scored 100 → **0** with a
   corrected evidence note; the Supreme Court claim's evidence note rewritten to cite the real
   *Watson* decision; the California claim's note stripped of the unverifiable AP reference;
   `score_adjustments.adjustment_reason` corrected. Overall score and categories unchanged at 95 —
   still justified, now on a citable basis.
4. **`grounding_metadata` on 3e53d8e1**: the three non-existent URLs replaced with
   `[citation removed 2026-09-19: URL not returned by any search and does not resolve; VER-388]`.
   `sos.ca.gov/elections/official-canvass` is real (HTTP 200) and was kept. The `web_research`
   narrative now opens with an `!! UNRELIABLE - DO NOT CITE !!` banner; the fabricated excerpts and
   source attributions were deliberately **left in place as evidence of the defect**.
   `evidence_gate` and `stage_3_verification_evidence` untouched, so `original_overall` survives.

Applied 20:16:35 UTC in one transaction via the Supabase Management API query endpoint.

## Verification after the write

- All three: `status = 'Processed'`, `overall = 95`, matching a pgroonga `fulton` search → still the
  top results on verdad.app.
- Rendered text contains no URLs, no "as confirmed by", no "no verification searches were run".
- `3e53d8e1`: Alito claim score = 0; `evidence_gate` and the 6-search Stage 3 log intact;
  only remaining URL in `grounding_metadata` is the real `sos.ca.gov` one.

## Rollback

```sql
-- restores the 20:05 post-score-restore state (pre-regrounding)
UPDATE snippets s
SET explanation = snap.explanation,
    confidence_scores = snap.confidence_scores,
    grounding_metadata = snap.grounding_metadata,
    updated_at = now()
FROM snippet_analysis_snapshot snap
WHERE snap.batch = 'regrounded-2026-09-19-carlos' AND s.id = snap.snippet;
```

To go further back — to the gate-capped state of 40 — use batch `unmask-2026-09-19-carlos`.

## Follow-ups (not done here)

- **Stage 4 invents citations when its searches return nothing.** Needs a tool-echo check on
  `web_research` of the kind PR #98 added for Stage 3: no URL may appear in the narrative unless it
  was returned by a recorded search. This is a code fix, and it is the highest-value one.
- **Re-audit the other 4 fabricating rows** originally 95+: `34b9799d`, `0759b76b`, `da72ac15`, `8a9516b8`.
- **The evidence gate is load-bearing, not merely conservative.** It is the only thing that stopped a
  95-confidence verdict built on invented sources — and a wrongly-labelled-false claim — from reaching
  a reporter. Any proposal to relax it should account for that.
- **VER-358 / the sub-95 population** is a separate product question: 5,353 Stage 3 caps since 09-16
  for no-contradicting-URL, 1,933 of them originally 95+. Those rows carry no invented citations;
  surfacing them is a threshold decision, not an accuracy fix.

Census figures in this document are kathmandu-98's, limited to rows updated since 2026-09-16
(a full-table scan of `grounding_metadata` times out).

## Addendum: broadcast date precision (applied 20:21 UTC)

`recorded_at` for `3e53d8e1` is 07:27 UTC on 10 Sep 2026 — 03:27 in Miami — and the host opens with
"buenas noches". The segment is therefore most likely a late-evening 9 September programme or its
overnight repeat, so the host's "hoy" probably means 9 September, not 10 September. The explanation
originally pinned it to the 10th. Both languages now state the capture time and local time, note the
ambiguity, and record that no ruling was issued on **either** date — which is what matters for the
verdict and is what a journalist pinning the date would need. (Caught by the drafting agent; the
Stage 3 log only ever queried 10 September, so a 9 September search is an obvious follow-up gap.)
