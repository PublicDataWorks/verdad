# Parallel Decisions API for VERDAD Stage 3 / Stage 4: evaluation

**Verdict: not a Stage 3 replacement and not a Stage 4 researcher replacement. At best a cheap, fast triage signal that can skip clear non-claims, and only after the retrieval problems below are handled.**

## Access
MCP `web_decisions` at `https://mcp.parallel.ai/mcp` works with no key (streamable HTTP, SSE responses) but has a free-tier rate limit. After 22 successful calls in a process, every call returned HTTP 429 with JSON-RPC `{"error":{"code":-32000,"message":"You've hit the free-tier rate limit for Parallel Search MCP. To continue with higher limits, add your own API key — set header x-api-key: YOUR_KEY or Authorization: Bearer YOUR_KEY. Get a key at https://platform.parallel.ai."}}`. Each variant ran as its own process, and fresh processes got through immediately, so the cap looks per session. A to D completed this way (38 each); once I saw the pattern I stopped rather than cycle sessions on purpose. Variant E stopped at 20 of 38 and the planned repeat-run noise test was not run. The client also works with `PARALLEL_API_KEY` against `POST https://api.parallel.ai/v1/decisions` (untested). No signup, no spend.
**No deeper mode exists:** the schema pins `mode` to `"fast"`, so the slow-mode comparison was impossible. One snippet rerun three times gave 0.876, 0.896, 0.88.

## Variants (all 3 questions: is_false noul, category choice over 15 production categories plus `none`, evidence_quality score on 5 levels mapped to 0 to 100)
- **A** as specified: station, state, recorded_at, language, flagged-segment transcript, production explanation. **B** A minus explanation. **C** no station, with explanation. **D** transcript only. **E** (20 snippets) D with neutral wording ("accurate according to reliable sources").

## Findings
1. **Station metadata hijacks retrieval.** In A and B, 59% and 60% of citations are about the radio station (Wikipedia KVIV, streema, mytuner, BBB, FCC). For d5dd1881 (West Bank sovereignty) A returned 0.81 with ten Monte Carlo Doualiya pages and zero on-topic sources, so the number came from the model's prior plus my pasted explanation. Every call returns exactly 10 citations for the whole request, with no per-answer mapping.
2. **The answer tracks the production explanation, not the evidence.** Mean p(false): A 0.60, C 0.63, B 0.19, D 0.30. Removing the explanation drops 0.7+ calls from 19 (A) to 0 (B). Example d43634ee ("Tonic promoted with false promise of cancer prevention"): A 0.86, C 0.92, B 0.03, D 0.04, E 0.13, (D cites generic cancer.gov and MedlinePlus pages). It needs the claim stated for it, which means Stage 1 already did the hard part.
3. **Question wording steers search.** With "false or misleading" and "misinformation category" in the questions (C, D), 27% and 36% of citation titles (regex heuristic) are generic misinformation or fact-check pages (mediabiasfactcheck.com appears 57 times in D). E (neutral wording) retrieved on-topic sources (PubMed, cancer.org, WHO, Catholic/Fox Noticias pages) but its answers got worse against production.
4. **Refusals: 0 of about 500 questions.** Latency 0.5 to 2.3 s, mean 0.70 s (Stage 3 rerun mean about 80 s). Input about 3.7k to 4.0k tokens per call.

## Agreement (p>=0.7 vs production overall>=80; n=38)
| variant | acc | kappa | Spearman | AUC | TP/FP/FN/TN |
|---|---|---|---|---|---|
| A | 0.63 | 0.26 | 0.42 | 0.69 | 8/11/3/16 |
| C | 0.66 | 0.30 | 0.49 | 0.75 | 8/10/3/17 |
| D | 0.76 | 0.24 | 0.46 | 0.78 | 2/0/9/27 |
| B | 0.71 | 0.00 | 0.36 | 0.76 | 0/0/11/27 |

The reference is weak: 14 of 38 clips have production overall <=40 but a 2.5-pro rerun >=85 (clear supplement claims scored 20 to 40 in production). Against the rerun (n=35, rerun>=80): A acc 0.63 (kappa 0.27), **C acc 0.77 (kappa 0.56)**, D 0.43. Category: top choice matches a production category on 17/36 (A), 16/36 (C), 12/36 (D).
**Human labels (22 labelled):** these are research-topic tags ("Texas research 2026: women & gender"), not truth verdicts, so "yes" means a person picked the clip. p>=0.7: A 10/22, C 11/22, D 0/22, E 8/20; production >=80: 5/22; rerun >=80: 13/22. The three labelled biblical-marriage clips (production 0) scored p<=0.15 everywhere, correctly. Unlabelled (16): A flags 9, production 6.

## Language behaviour
Spanish and Arabic retrieve natively when the query is claim-centric: in D, 36% of Arabic-claim citations are Arabic-script pages and 40% of Spanish-claim citations are Spanish, the rest English. Best case 0059ad0e (Starmer, Arabic): D returned BBC Arabic, Al Arabiya, Al Hadath and France24 items from June to Oct 2026 (BBC Arabic: Starmer announced his resignation on 22 June 2026; Andy Burnham is PM), so the bulletin's "still PM" claim scored p=0.94 false. A recency win a static model could not give. With station metadata (A/B) citations are 89 to 90% English for Arabic claims and 66 to 70% for Spanish, because station pages are English.

## Five disagreements
1. **d5dd1881** (Arabic, West Bank 80%): production 20, rerun 85, A 0.81, D 0.35. A's evidence is all station boilerplate; D's top hits are MBFC daily fact-check digests and a 2023 HRW piece ("The videos were horrifying, and they were real"), none about West Bank sovereignty. Thin/off-topic citations behind a confident number.
2. **d43634ee** (Canutri cancer prevention): production 40, rerun 95. A 0.86 versus D 0.04: same claim, opposite answers depending on whether my explanation is in the prompt.
3. **e8d3c562** (tubal ligation death anecdote): production 80, rerun 40, A 0.10, D 0.11. D's sources are a Relevant Radio episode and an Arizona court judgment about a different matter ("She did not testify that the Plaintiff made a specific, affirmative statement that she could not become pregnant"). Calling an anecdote unfalsifiable is defensible; the retrieval is not.
4. **998bd8f1** (vote against Democrats, "communists"): production 40, rerun 95, A 0.53, D 0.06. D cites an Israel election results page and a Frontiers paper defining disinformation ("verifiably false or misleading information created... for economic gain"), nothing on the claim.
5. **0059ad0e** (Starmer): agreement, production 85, D 0.94, as above, with real on-point Arabic sources.

## Cost
$0.001 per request: $0.001 per snippet for 3 questions (all questions share one search), $0.038 per 38. Stage 3 costs $0.29 to $0.46 per clip, 300x to 460x more. Cost is not the constraint; accuracy and controllability are.

## Recommendation by placement
- **Pre-check before Stage 3 (only viable use).** Run C-style (claim stated, no station) and skip Stage 3 when p(false)<0.15. At that cutoff A skipped 4 of 38 clips (1 production-positive), C 3 (0), D 8 (4 rerun-positive). That is a saving of roughly 10% of clips at best, with real false-negative risk; 38 clips cannot set thresholds. I did not test evidence_quality as a second gate, though its mean fell when retrieval was off-topic (A 22, C 38, D 32).
- **Evidence supplier to Stage 3.** Possible only with claim-centric state and neutral wording (E retrieved on-topic sources). You cannot pin domains, require agencies or map a citation to an answer, so Stage 3 still needs its own reads. Finish E on all 38 with a key before deciding.
- **Stage 4 replacement: no.** Stage 4 needs targeted source selection and an evidence gate (it has fabricated citations before); Decisions offers no source control, and a decisive probability can sit on generic or absent evidence.
- **Risks:** answers from prior rather than evidence (1, 2), generic-research retrieval (3), free tier capped near 22 calls per session, English-leaning retrieval when metadata is English, no per-claim citation mapping, long transcripts need the claim isolated first.

## Files
Code: `eval/parallel_decisions_eval.py`, `parallel_analyze.py`, `parallel_metrics.py`. Raw: `eval/results_parallel/<snippet>.{A..E}.json` (E: 20 snippets plus 2 stored 429 stubs).

## Per-snippet table (A = as specified; C and D p(false) for comparison; every call returned 10 citations and no refusals)
| id | title | lang | human | prod S3 | rerun S3 | A p(false) | C | D | cites | lat A s | refusal |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 12a7bb8c | Promotion of 'Immunocal' Supplement for Ne | Sp | yes | 40 | 98 | 0.88 | 0.80 | 0.50 | 10 | 0.6 | no |
| 2c1c1c66 | Promotion of "Canutri K21" Tonic with Unve | Sp | yes | 20 | 95 | 0.44 | 0.40 | 0.17 | 10 | 0.7 | no |
| d43634ee | Tonic Promoted with False Promise of "Canc | Sp | yes | 40 | 95 | 0.86 | 0.92 | 0.04 | 10 | 0.7 | no |
| 3734c9ae | Speaker Claims Women's Health Has Not Wors | En | yes | 85 | 90 | 0.78 | 0.75 | 0.25 | 10 | 0.7 | no |
| 289da693 | False Claims About Physiological Consequen | En | yes | 85 | 90 | 0.91 | 0.91 | 0.41 | 10 | 0.8 | no |
| e8d3c562 | Unverified Anecdote Links Tubal Ligation t | En | yes | 80 | 40 | 0.10 | 0.25 | 0.11 | 10 | 0.6 | no |
| 79974d13 | Speaker Accuses Democrats of Supporting Ki | Sp | yes | 95 | fail | 0.89 | 0.92 | 0.50 | 10 | 0.6 | no |
| 998bd8f1 | Call to Vote Against Democrats, Accused of | Sp | yes | 40 | 95 | 0.53 | 0.36 | 0.06 | 10 | 0.6 | no |
| 7689727d | Radio Ad Promotes 'Tónico K21' Supplement  | Sp | yes | 20 | 95 | 0.40 | 0.59 | 0.22 | 10 | 1.0 | no |
| aeb36905 | 'Immunocal' Supplement Dangerously Promote | Sp | yes | 40 | 95 | 0.82 | 0.78 | 0.43 | 10 | 0.8 | no |
| 3a049b4c | Religious Speaker Tells Woman to Ignore Ca | Sp | yes | 20 | 95 | 0.59 | 0.82 | 0.12 | 10 | 0.9 | no |
| 455799a2 | Testimonies of Divine Healing and Criticis | Sp | yes | 20 | 40 | 0.46 | 0.52 | 0.06 | 10 | 0.6 | no |
| d098eaac | Testimony of Miraculous Healing of Uterine | Sp | yes | 40 | 95 | 0.88 | 0.86 | 0.28 | 10 | 0.8 | no |
| 12d96c9b | Speaker Uses Pseudoscience About Finger Le | Sp | yes | 85 | 85 | 0.94 | 0.87 | 0.33 | 10 | 0.8 | no |
| 368296fa | Claims on the Dangers of Contraception and | En | yes | 20 | 40 | 0.46 | 0.33 | 0.22 | 10 | 0.6 | no |
| 06547eab | Biblical Roles in Marriage: The Husband as | Sp | yes | 0 | 0 | 0.03 | 0.14 | 0.14 | 10 | 0.6 | no |
| 262e70e7 | Religious Critique of Feminism and Exhorta | Sp | yes | 0 | 0 | 0.05 | 0.09 | 0.15 | 10 | 0.7 | no |
| 505d35f7 | God's Design for Marriage: Leadership and  | Sp | yes | 0 | 0 | 0.03 | 0.05 | 0.02 | 10 | 0.7 | no |
| 5ef8db75 | Apocalyptic Predictions About a Democratic | Sp | yes | 20 | 90 | 0.18 | 0.22 | 0.07 | 10 | 1.0 | no |
| 6a694119 | Speaker Accuses Democrats of Being Anti-Ch | Sp | yes | 20 | 85 | 0.78 | 0.84 | 0.25 | 10 | 0.7 | no |
| c3a9d17d | Voting for Democrats is Voting to Castrate | Sp | yes | 20 | 40 | 0.83 | 0.86 | 0.50 | 10 | 0.7 | no |
| d779fb56 | Voting for Democrats Makes You an Accompli | Sp | yes | 40 | 40 | 0.33 | 0.30 | 0.18 | 10 | 0.7 | no |
| 61fdcdf4 | Analysis of Israel's Geopolitical Strategy | Ar | no | 0 | 35 | 0.24 | 0.49 | 0.16 | 10 | 0.6 | no |
| d5dd1881 | Claim that Israel Has Imposed Sovereignty  | Ar | no | 20 | 85 | 0.81 | 0.87 | 0.35 | 10 | 0.8 | no |
| 0059ad0e | News bulletin claims Keir Starmer is still | Ar | no | 85 | 90 | 0.84 | 0.97 | 0.94 | 10 | 0.7 | no |
| 32bb1f75 | Arrival of Cruise Ship with Hantavirus Out | Ar | no | 15 | 75 | 0.76 | 0.63 | 0.35 | 10 | 0.6 | no |
| 568941be | Iranian Leader Meets with Military Command | Ar | no | 0 | 40 | 0.88 | 0.66 | 0.24 | 10 | 0.7 | no |
| 5adafdf1 | Military Expert Claims Israel Plans to Eva | Ar | no | 20 | 35 | 0.45 | 0.66 | 0.57 | 10 | 0.7 | no |
| a45f1f4e | News Bulletin on US and World Affairs | Ar | no | 0 | 0 | 0.79 | 0.64 | 0.20 | 10 | 0.8 | no |
| 8bca86ce | Iran Delivers Response to US Proposal, Emp | Ar | no | 10 | 0 | 0.55 | 0.49 | 0.34 | 10 | 0.9 | no |
| 8ffce2fc | Promotion of NAD Supplement with Unverifie | Sp | no | 95 | fail | 0.80 | 0.93 | 0.86 | 10 | 0.6 | no |
| d8704093 | Testimony of Divine Healing: Expulsion of  | Sp | no | 20 | 95 | 0.90 | 0.95 | 0.35 | 10 | 0.7 | no |
| 276050ab | Promotion of 'Miracle Tonic' for Newborns  | Sp | no | 90 | 95 | 0.40 | 0.60 | 0.22 | 10 | 0.5 | no |
| a3d01d5d | Promotion of an herbal tonic 'Canutri K21' | Sp | no | 20 | 95 | 0.52 | 0.76 | 0.22 | 10 | 0.6 | no |
| 47dd8ade | False Claim About Link Between Vasectomy a | En | no | 95 | fail | 0.91 | 0.85 | 0.41 | 10 | 0.8 | no |
| 0358fb14 | Radio Ad Promotes 'Canutri K21' Supplement | Sp | no | 98 | 95 | 0.45 | 0.64 | 0.51 | 10 | 0.7 | no |
| a6aea28a | Product 'Immunocal' Falsely Promoted as Sa | Sp | no | 40 | 90 | 0.60 | 0.42 | 0.17 | 10 | 0.6 | no |
| f74e0af3 | NAD Supplement Promoted as a Cure for Canc | Sp | no | 95 | 85 | 0.86 | 0.87 | 0.49 | 10 | 0.7 | no |