# Stage 1 detection prompt tuning for Gemini 3.x and Gemma 4

**Result.** v4 takes gemini-3.8-flash@low from 12 to 14/22 human-labelled snippets up to 16/22, matching 2.5 Flash. It scored 16 on every v2 and v4 run. Flags per file go from 1.6 to 2.9, the new flags are real claims, and cost drops 15%. Flash-Lite@low goes from 1 to 5 to 11/22. Gemma 26B goes from 10 to 14 to 14 or 15, with a few new false flags. Gemma 31B goes from 11 to 12/13 (6 files). Keep the production prompt for 2.5 Flash. The maximum is 20/22, because 2 labelled snippets are absent from production's flags.

## Why 3.x under-flagged

3.8@low still catches egregious claims but drops ones that are unsubstantiated rather than provably false (a tonic for pregnancy, the Dobbs health claim, finger length). The system instruction and Self-Review require "demonstrably false" four times. 2.5 ignored that; 3.x applies it literally. Nothing says Stage 3 verifies every flag, and both examples are egregious. Output budget is not the cause (at most 1.4k of 16k tokens). Details are in `prompts_tuning/NOTES.md`.

## Variants (schema and placeholders unchanged)

- **v1**: recall-first system instruction and Self-Review (screening stage; a later stage fact-checks).
- **v2**: v1 plus three hypothetical must-flag borderline examples and two do-not-flag rules (unfamiliar current events; opinion or faith with no factual claim).
- **v3**: v2 plus "go in order, one flag per distinct claim".
- **v4**: v2 minus the per-category keyword lists and the inline JSON schema (11.2k vs 14.1k input tokens).

## Results (18 files, human-hit /22; one value per run)

| model | prompt | human-hit | flags/file | prec@prod | $/file | s/file |
|---|---|---|---|---|---|---|
| 3.8 Flash@low | prod (3 runs) | 13, 14, 12 | 1.5 to 1.7 | 0.93 to 1.00 | 0.013 | 5 to 8 |
| | v1 | 16, 13 | 2.7, 2.9 | 0.94, 0.90 | 0.014 | 7 to 8 |
| | v2 | 16, 16 | 2.8, 2.6 | 0.92, 0.93 | 0.014 | 7 |
| | v3 | 16 | 2.7 | 0.94 | 0.014 | 7 |
| | **v4** | **16, 16** | 2.7, 3.1 | 0.92, 0.93 | **0.011** | 7 to 8 |
| 3.5 Flash-Lite@low | prod (3 runs) | 4, 1, 5 | 0.3 to 0.5 | 1.00 | 0.004 | 1 |
| | v1 | 7, 5 | 1.6, 1.1 | 0.93, 0.95 | 0.005 | 1 to 2 |
| | v2 | 10, 8 | 1.5, 1.2 | 0.93, 0.95 | 0.005 | 2 |
| | v3 | 10 | 1.4 | 0.92 | 0.005 | 2 |
| | **v4** | **11, 11** | 1.8, 1.7 | 0.97 | 0.004 to 0.005 | 2 |
| Gemma 26B (Vertex) | prod (3 runs) | 12, 14, 10/20* | 2.8 to 3.1 | 0.90 to 0.92 | n/m | 8 to 11 |
| | v1 | 15 | 3.6 | 0.91 | n/m | 11 |
| | v2 | 15, 15 | 3.4, 3.8 | 0.87, 0.93 | n/m | 10 to 11 |
| | v3 | 13 | 3.9 | 0.89 | n/m | 17 |
| | **v4** | **15, 14** | 3.6, 2.9 | 0.91, 0.94 | n/m | 9 to 10 |
| Gemma 31B (API, 6 files, /13) | prod | 11/13 | 3.8 | 0.91 | free | 26 |
| | **v4** | **12/13** | 5.7 | 0.76 | free | 38 (429 waits) |
| | v2 | 12/12 (5 files, 1 failed on 429) | 6.4 | 0.75 | free | 41 |
| 2.5 Flash | prod | 16 | 7.0 | 0.90 | 0.018 | 25 |
| | v2 | 17 | 10.3 | 0.77 | 0.020 | 28 |
| | v4 | 18 | 12.8 | 0.75 | 0.020 | 29 |

\* One file failed. n/m: Vertex Gemma is not metered by the harness (about 1.94M input and 0.11M output tokens in total). Gemini API spend was **$3.19**.

v1 alone is unstable (3.8: 16 then 13; Lite: 7 then 5). The calibration examples make the gain hold. v3 adds nothing and hurts Gemma 26B. v4's cut costs nothing.

## Recommendation per model

- **3.8 Flash@low: v4.** Same hits as v2 and v3, 15% cheaper per file (22% fewer input tokens).
- **3.5 Flash-Lite@low: v4.** Best variant, but 11/22 is still short of 16. It misses the faith-healing file and finger length.
- **Gemma 26B: v4** (v2 ties). The gain is near run-to-run noise and adds a few false flags.
- **Gemma 31B: v4.** Fewer free-tier 429s (10.8k vs 13.8k tokens). Small sample.
- **2.5 Flash: keep the production prompt.** Under v4, e7ce9dcd goes from 0 to 21 flags, including stale-knowledge errors like "Merz is not Chancellor".

## v4 vs production (abridged unified diff)

```diff
--- prompts/stage_1/main/detection_system_instruction.md
+++ v4/detection_system_instruction.md
-Your role is to identify specific, demonstrably false claims while carefully distinguishing between controversial content and actual disinformation. You must provide detailed evidence ...
+You are the screening stage of a pipeline: every snippet you flag is fact-checked in depth by a later verification stage, which discards flags that turn out to be accurate. Your role is to surface every claim that is plausibly false, unsubstantiated, or misleading in a way that could harm listeners, without flagging pure opinion or statements of faith that make no factual claim. You must provide clear evidence ...
--- detection_user_prompt.md   (+26 / -328 lines)
-```json ...56-line inline schema...```
+The output schema is enforced by the API; return only the `flagged_snippets` object.
-**Keywords/Phrases**: ...            (removed in all 23 categories; Description/Heuristics/Examples kept)
+# Calibration: What Clears the Bar      (inserted before Self-Review)
+Flag a claim when a fact-checker would want to check it and it is likely false, unsupported by evidence, or misleading. It does not need to be provably false from the transcription alone. Hypothetical borderline cases that MUST be flagged:
+- Health or product claim without evidence: "Este té de moringa limpia la sangre, previene la diabetes y lo pueden tomar las embarazadas y los bebés sin ningún riesgo." ...
+- Pseudoscience or folk belief stated as medical fact: "Si usted se baña con el estómago lleno le da una embolia, eso está comprobado por los médicos." ...
+- Distorted characterization of a party, group or policy stated as fact: "Los republicanos quieren quitarle el Seguro Social a todos los jubilados." ... Apply the same standard whichever side is targeted.
+Do NOT flag: news about current events or office-holders only because you do not recognize them (treat the recording date as the present); opinions, prayers, or religious teaching that make no factual claim.
-1. **False Claims Verification** ... demonstrably false? ... If any answer is "no," reconsider flagging the snippet.
+1. **Coverage Check** ... flagged every plausibly false, unsubstantiated, or misleading claim, even when I cannot prove it false from the transcription alone? A missed claim costs more than a flag that turns out to be accurate. ... add the missing snippets.
-   - [ ] Each flagged snippet contains demonstrably false claims / ... defensible to fact-checkers
+   - [ ] ... at least one specific claim that is plausibly false, unsubstantiated, or misleading
+   - [ ] I have not skipped a claim only because it is not demonstrably false
```

The exact files are in `prompts_tuning/v4/`. Before production, confirm the Stage 1 executor passes `response_schema`, since v4 drops the inline schema.

## Per-file changes (v4; baseline = 3 prod runs, variant = 2 runs)

**3.8 Flash@low.** Newly caught:
- "Promotion of 'Canutri K21' Tonic with Unverified Health Claims for Disease Prevention and Pregnancy" (0/3 to 2/2)
- "Radio Ad Promotes 'Tónico K21' Supplement with Unverified Health Claims for Pregnant Women" (0/3 to 2/2)
- "Speaker Uses Pseudoscience About Finger Length to Define Gender" (0/3 to 2/2)
- "Speaker Claims Women's Health Has Not Worsened in Pro-Life States Post-Dobbs Decision" (1/3 to 2/2)

Lost:
- "Voting for Democrats Makes You an Accomplice to Murder and Puts You Against God" (3/3 to 1/2)
- "Tonic Promoted with False Promise of 'Cancer Prevention'" (2/3 to 1/2)

Flags with no production match are real claims (stop your prescriptions; "Costa Rica has no police"; misoprostol is reversible). Arabic news got 0 flags.

**Missed by every model and prompt:** both e14c4df8 "Biblical Roles in Marriage" snippets. That is framing, not a factual claim, so it needs a heuristic.

**Flash-Lite@low.** 9 snippets go from 0/3 to 2/2, including both Immunocal-for-newborns snippets, both K21-for-pregnancy snippets, contraception, and vasectomy/tubal ligation. Loss: "Voting for Democrats is Voting to Castrate Children and Kill Babies" (3/3 to 1/2).

**Gemma 26B (v2 and v4, 4 runs).** Gains:
- "Religious Speaker Tells Woman to Ignore Cancer Diagnosis…" (1/3 to 4/4)
- "Testimonies of Divine Healing…" (1/3 to 3/4)
- the K21 pregnancy ad (1/3 to 3/4)

New false flags:
- a law-firm ad "Is the specter of deportation haunting you?" (3 of 4 runs)
- "Mahmoud Rice makes you thin" (marginal)
- the sermon line "free love doesn't exist"
- a health-unit ad flagged with an explanation saying it makes no claims (v2)

**Gemma 31B.** Gains the K21 pregnancy ad. Its extra flags are redundant per-claim splits of one ad.

## Files

The harness (`eval/detection_eval.py`) adds `--prompt-dir` and `--tag`, plus a fallback to application-default credentials for Vertex because the gcloud user login needs interactive reauth. The original is in `prompts_tuning/detection_eval.orig.py`. Variants, `NOTES.md`, `make_variants.py` and the analysis scripts are in `eval/prompts_tuning/`. Results are in `eval/results_detection/<model>[@low]+<tag>/`.

Repo `prompts/` untouched, nothing committed, no production Supabase calls.
