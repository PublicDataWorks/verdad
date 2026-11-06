# Stage 1 detection prompt tuning for Gemini 3.x / Gemma 4: notes

## What the existing results show (before any change)

Per-file comparison (compare.py gemini-2.5-flash,gemini-3.8-flash@low):

- 3.8 Flash@low is not missing the egregious claims. It catches "cancer is a fungus", "give Immunocal to
  newborns", "prayer dissolved uterine tumours", "Democrats castrate children". What it drops are the
  *unsubstantiated* or *misleading* claims that are not provably false in one sentence:
  - K21 tonic recommended for pregnant women / people trying to conceive (04ec4773 16:00, 6dab0a83 18:19)
  - "women's health has not suffered in pro-life states since Dobbs" (2b167e0f 04:54); 3.8 instead flagged a
    different region (abortion pill reversal)
  - finger-length ratio tells you someone's sex (c6198e5d 08:02): 0 flags on the file
  - "Democrats want nothing to do with God / Israel / the Bible" (f3e1ad44 03:20)
  - preacher on wifely submission (e14c4df8): every model misses it, incl. the 2.5 rerun; this is framing, not
    a factual claim, and probably needs a heuristic rather than calibration.
- 3.8@low reports thoughts_token_count = 0 and ~5 s latency: at `low` it is effectively answering without a
  reasoning pass, so any "enumerate first" instruction has to work inside the output, not in thinking.
  Output budget is not the constraint (3.8@low outputs 12 to 1,400 tokens of a 16k cap).
- 3.8 merges neighbouring claims into one 40 s to 3 min span (06:20-09:20). Fewer flags/file, but the
  human-hit metric tolerates it; this is not the main recall loss.
- The 2.5 rerun's extra flags on the Arabic news files (9b261e47, 0613720a, 3d74caac, 19dafaf6) are mostly
  knowledge-cutoff errors ("Assad is still president", "Merz is not chancellor", "Makary is not FDA
  commissioner"). 3.8 correctly flags nothing there. A recall-first prompt must not reintroduce these, so
  these four files are the false-flag guardrail.
- Ceiling: 2 of the 22 human-labelled snippets (262e70e7, e8d3c562) are not in the production
  flagged_snippets, so `report` can never count them; max human-hit is 20/22.
- Human labels are mostly "women & gender" plus "elections": supplement ads, faith healing, contraception
  myths, election sermons. The labelled set rewards flagging unsubstantiated health claims and misleading
  political characterisations, not only provably false statements.

## Hypotheses for why 3.x under-flags

H1 (strongest). The **Self-Review Process** is a precision filter that 3.x executes literally: "specific,
   verifiably false", "would a reasonable person agree these claims are demonstrably false?", "If any answer
   is 'no', reconsider flagging", "Each flagged snippet contains demonstrably false claims", "defensible to
   fact-checkers". 2.5 Flash treated this as boilerplate; 3.x drops every unsubstantiated-but-not-disproven
   claim.
H2. The **system instruction** puts the same bar in the highest-priority slot: "identify specific,
   demonstrably false claims while carefully distinguishing between controversial content and actual
   disinformation". Nothing anywhere says Stage 1 is a screening pass and that Stage 3 verifies each flag.
H3. The **two worked examples** are both egregious (plandemia microchips, "illegal aliens cause economic
   problems"), so 3.x calibrates its threshold to the most obvious cases. No example shows a borderline
   claim that must still be flagged (unsubstantiated supplement claim, misleading partisan characterisation,
   pseudoscience stated as fact).
H4. At `low` thinking there is no reasoning pass over a 30-minute transcript; the model emits the 1 to 3 most
   salient items and stops. An explicit "go window by window, one flag per distinct claim" instruction may
   recover more; it may also add noise.
H5 (Gemma only). The 34 KB user prompt (~9k tokens of heuristics with repeated keyword lists) dilutes the
   instruction for a 26B/31B model and doubles input against the 16k TPM free tier. The JSON schema is also
   repeated inline although it is enforced by response_schema.
H6 (risk). Lowering the bar may make 3.x flag accurate 2026 news it cannot verify (the 2.5 failure mode on
   Arabic news). The variants need an explicit "do not flag news merely because you do not know it" line.

Not the cause: output token budget (H rejected from token counts above); KB section (kb_context is empty in
the eval and in most production calls).

## Variants (prompt text only; schema and placeholders unchanged)

- v1 = H1 + H2: rewrite the system instruction and the Self-Review section to recall-first (screening pass,
  Stage 3 verifies, flag plausibly false / unsubstantiated / misleading). Everything else identical.
- v2 = v1 + H3 + H6: add a short "Calibration" section with three borderline must-flag examples (deliberately
  not taken from the eval files) and one do-not-flag rule for unfamiliar current events.
- v3 = v2 + H4: add a "go through the transcript in order, one flag per distinct claim, do not merge claims
  more than about a minute apart" instruction.
- v4 = v2 + H5: same instructions as v2, heuristics condensed (keyword lists and inline JSON schema dropped)
  to cut input tokens for Gemma.

## Results log
(appended after runs)

### Results (human-hit /22 on 18 files unless noted; each number is one run)
- 3.8 Flash@low: prod 13, 14, 12 | v1 16, 13 | v2 16, 16 | v3 16 | v4 16, 16
- 3.5 Flash-Lite@low: prod 4, 1, 5 | v1 7, 5 | v2 10, 8 | v3 10 | v4 11, 11
- Gemma 26B (Vertex): prod 12, 14, 10/20 | v1 15 | v2 15, 15 | v3 13 | v4 15, 14
- Gemma 31B (API, 6 files, /13): prod 11 | v4 12 | v2 12/12 (5 files)
- 2.5 Flash: prod 16 | v2 17 | v4 18, but flags/file 7.0 -> 10.3 / 12.8 and knowledge-cutoff flags on Arabic news grow
  (e7ce9dcd 0 -> 21 under v4: "Merz is not chancellor", "Mojtaba is not Supreme Leader").

Verdict on hypotheses: H1+H2 (v1) help but are unstable alone (3.8: 16 then 13; Lite: 7 then 5). Adding H3
calibration examples (v2/v4) makes the gain stable. H4 (v3, in-order pass) adds nothing on 3.8/Lite and hurts
Gemma 26B (13). H5 (v4, 30% shorter) costs nothing and is slightly best on Lite; cuts input 14.6k -> 11.2k tokens.
H6 holds: no variant made 3.x flag the Arabic news files (0 flags in every 3.x variant run).
Harness change also needed: gcloud user creds required interactive reauth, so call_vertex falls back to ADC.
