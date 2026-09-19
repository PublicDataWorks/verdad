# Handoff: the 3 Fulton County clips for Carlos Chirinos

Date: 2026-09-19
Author: Claude (session `session_01RbFdV1RH3zCkU5y5JZ4bnp`), for Rajiv Sinclair

Plain-file version of the briefing artifact `carlos_fulton_briefing.html`
(`https://claude.ai/artifact/LH8gxjw5vQ3Lme5dPFqHse`), created because the artifact link is not
reachable by other Claude agents/sessions due to platform security restrictions. Use this file
instead when coordinating the "unhide the snippets relevant to Carlos" work.

## What this is for

Carlos Chirinos (palabra reporter, story publishing next week) searched VERDAD for Fulton
County, GA election-fraud disinformation and found nothing after July 24. The three snippets
below are what our system found and correctly flagged, but they are not visible in the app's
search because of the evidence-gate/publication-threshold issue described in
`docs/HANDOFF_2026-09-19_visibility_vs_verdict_design.md`. The task for whoever picks this up:
unhide/surface these three specific snippets so they are searchable in verdad.app, per Rajiv's
explicit product direction ("our system should not hide them, it should analyze them and explain
correctly when they are misleading").

## The three snippets

All three are from one continuous broadcast segment, Radio Mundo (Florida), September 10, 2026,
07:24-07:32 UTC. All three currently score 40/100 (capped by the evidence gate) and are not
visible in app search.

1. **`fb43bf56-692d-4a68-8d96-edb029854bd2`** — 07:24 UTC — "Dominion, China, and the 2020
   election." Fabricated claim that Maduro will testify in a federal RICO case against US
   officials over 2020 election rigging; recycled Dominion/China conspiracy theory.
2. **`c253e70f-c00a-4ba2-8e15-bd66cf458574`** — 07:25 UTC — "Maduro to testify against Kemp,
   Raffensperger, Whitmer." Names Brian Kemp and Brad Raffensperger (Georgia) and Gretchen
   Whitmer / Jocelyn Benson (Michigan); claims Fulton County "recognized" violating 1.7 million
   votes in Georgia. No such recognition exists.
3. **`3e53d8e1-fdbd-4c4c-a692-f34be0b10962`** — 07:27 UTC — Fabricated September 2026 Supreme
   Court ruling on mail-in voting, plus a fabricated Justice Alito quote (independently debunked
   by PolitiFact and FactCheck.org as a recurring recycled fabrication).

Full Spanish transcripts, English translations, and per-clip "why this is false" analysis for
all three are in the artifact HTML (`carlos_fulton_briefing.html`, also attached in this session's
scratchpad) — reproduce from there if the raw text is needed; omitted here to keep this handoff
short.

## Why they're hidden today (context, not yours to re-litigate)

The evidence gate (`apply_evidence_caps()`, `src/processing_pipeline/stage_3/models.py`) caps a
`verified_false` verdict's score unless a search result is marked `relevance_to_claim ==
"contradicts_claim"`. None of these three have such a source — claims this hyper-local rarely get
a dedicated fact-check article. That's the structural problem tracked in VER-358 and detailed in
`docs/HANDOFF_2026-09-19_visibility_vs_verdict_design.md`. Fixing that gate properly is a larger,
separate piece of work. This handoff is scoped narrower: get these 3 specific, already-verified
snippets visible now, by whatever safe mechanism the other agent judges appropriate (e.g. a manual
override/exception rather than reworking the gate itself), without reintroducing the earlier
"wrongly labeled false" problem the gate was built to prevent.

## Constraints

- Do not lower the evidence-gate threshold globally — see "What NOT to do" in
  `docs/HANDOFF_2026-09-19_visibility_vs_verdict_design.md`.
- Do not touch `src/processing_pipeline/*/flows.py`, `supabase/migrations/`, `fly.*.toml`, or
  `Dockerfile.*` without plan mode first (`CLAUDE.md`).
- Never deploy, run migrations, or write to production data without explicit confirmation
  (`AGENTS.md` Rules section).
- These three snippets are independent of the VER-389 stuck-error-queue issue (PR #118) — do not
  conflate the two; clearing that queue does not affect these three.

## Status of the letter/artifact to Carlos

Martina and Tamoa have already been told (letter, forwarded to Carlos) that we are actively
reversing the rule keeping these hidden, and that we are sending the clips directly in the
meantime. Once these are actually visible in the app, report back so we can confirm the search
link works and follow up with Carlos.
