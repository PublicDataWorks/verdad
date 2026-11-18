# gemini-3.5-transcribe request options: language_codes and diarization

Date: 2026-11-01. Harness: `scratchpad/eval/harness.py transcribe --variant {lang,diar,lang+diar,repeat}`,
results in `scratchpad/eval/results/gemini-3.5-transcribe@<variant>/` (with `.raw.json` API responses), per-file
rows in `results/summary_transcribe_options.json`.

## Recommendation

**Keep production's current request:** `mode: {type: verbatim, timestamp_granularities: ["word"]}`, with no
`language_codes` and no `diarization_mode`.

- Neither option moves transcript quality beyond run-to-run noise. Sending the identical baseline request a second
  time (`repeat`) moved mean window similarity by +0.7 and single files by up to +2.9. Every variant lands inside
  that band in aggregate, and the per-file changes don't point the same way.
- `language_codes` costs something in principle and showed no gain in practice. The docs say auto-detection
  "handles code-switching"; a fixed locale is a bet against that on stations that run English ads in Spanish
  programming, and `ar-EG` is the wrong dialect for MCD (pan-Arab, Paris) and probably ARAB too. Arabic WER with
  `lang` alone was the worst of the five runs (0.304 vs 0.238 to 0.257 for the two baseline runs), but with n=2 that
  is a hint, not a finding.
- Diarization fails silently on some files and over-segments the rest (details below). It adds no latency or tokens,
  but it is not reliable enough to depend on.

**Speaker labels in the detection prompt: not now.** Turn *boundaries* are plausible, but speaker *identities* are
not stable or bounded, and some responses carry no labels at all, so a prompt that relied on them would see different
input shapes for the same kind of audio. If speaker context is wanted later, the cheaper option to evaluate is a line
break at each turn change in the transcript, not `spk:N` tags, and only after diarization is re-checked on a model
update. `transcribe_executor.py` already stores `speaker` per word (null today), so nothing is lost by waiting.

## Runs

6 recordings, 30 min each (trimmed to 1799 s): Spanish 6dab0a83 (KVIV 1340 AM), fa372ac7 (KCMT 92.1 FM); Arabic
9b261e47 (ARAB), 3d74caac (MCD); English 2b167e0f, 301a98e3 (KYAR 98.3 FM). Reference = the production
gemini-2.5-flash segment transcript (not ground truth). Variants:

| variant | request change |
|---|---|
| baseline | (existing `results/gemini-3.5-transcribe/`, from the earlier eval) |
| repeat | baseline body sent again: measures run-to-run noise |
| lang | `language_codes`: Spanish `["es-US"]`, Arabic `["ar-EG"]`, English `["en-US"]` |
| diar | `mode.diarization_mode: "speaker"` |
| lang+diar | both |

## Results (means over 6 files)

| variant | window sim | p>=70 | WER vs ref | words/file | empty windows | request s | wall s | output tokens |
|---|---|---|---|---|---|---|---|---|
| baseline | 93.5 | 0.972 | 0.172 | 3,834 | 2.0% | n/a | 56.9 | 5,588 |
| repeat | 94.2 | 0.978 | 0.166 | 3,836 | 1.5% | 54.3 | 56.9 | 5,602 |
| lang | 92.7 | 0.965 | 0.190 | 3,817 | 2.8% | 54.0 | 56.7 | 5,558 |
| diar | 92.8 | 0.969 | 0.183 | 3,810 | 2.2% | 55.2 | 57.9 | 5,529 |
| lang+diar | 94.2 | 0.978 | 0.182 | 3,896 | 1.7% | 56.3 | 58.9 | 5,621 |

"Empty windows" = share of 20 s windows that have text in the reference but none in the candidate. "Request s" =
the interactions POST alone; "wall s" adds the Files API upload. Input tokens are identical (44,977/file); cost is
per audio minute, $0.15/file for every variant.

Per-file window-similarity change vs baseline:

| file | language | repeat | lang | diar | lang+diar |
|---|---|---|---|---|---|
| 6dab0a83 | es | 0.0 | 0.0 | -0.1 | -0.4 |
| fa372ac7 | es | **+2.9** | -0.1 | +2.8 | +0.9 |
| 9b261e47 | ar | 0.0 | -4.6 | -4.8 | +3.8 |
| 3d74caac | ar | +1.3 | -0.3 | -1.5 | +0.2 |
| 2b167e0f | en | -0.3 | -0.3 | -0.3 | -0.3 |
| 301a98e3 | en | +0.1 | +0.1 | -0.1 | +0.2 |

By language (window sim / WER): Spanish base 91.2/0.172, repeat 92.7/0.168, lang 91.2/0.184, diar 92.5/0.171,
lang+diar 91.4/0.235. Arabic base 90.8/0.257, repeat 91.5/0.238, lang 88.4/0.304, diar 87.7/0.293, lang+diar
92.8/0.222. English is flat at 98.3 to 98.5 and 0.082 to 0.091 everywhere.

On 9b261e47, `lang` and `diar` each lost about 4.7 points while `lang+diar` gained 3.8. Opposite signs from options
that overlap mean this file's spread is noise (probably the music and jingle windows, which carry the empty-window
share), not an option effect.

**Shift test:** in every variant the 0 s alignment beats +/-20 s on 6/6 files, with a margin of at least 40.6 points.
No option affects timestamp alignment.

## Diarization behaviour

- **Silent no-op on one file.** 6dab0a83 (KVIV talk) came back with `speaker` absent on all words in both `diar`
  and `lang+diar`; the request was accepted (HTTP 200). Probes on cuts of the same file: the 20 s, 5, 10, 15 and
  25 min cuts returned labels, the 20 min cut returned none. The field is recognized (a bogus field in `mode` gets
  HTTP 400 "Unknown parameter"; `"SPEAKER"` in caps is accepted and also silently ignored), so this is the model
  dropping diarization, not a request error.
- **Over-segmentation.** Distinct speakers per file: 23 and 20 (2b167e0f), 14 and 14 (301a98e3), 7 and 8 (3d74caac),
  8 and 14 (9b261e47), 9 and 8 (fa372ac7) for diar / lang+diar. The docs give a maximum of 8 and call 3+
  experimental. Radio has many real voices (ads, promos, callers), so some of this is real, but the long tail of
  speakers with 5 to 50 words looks like fragmentation.
- **Labels are not stable across runs.** Same file, two requests: 301a98e3 `spk:9` has 983 words in `diar` and 217 in
  `lang+diar`, and 9b261e47 goes from 8 to 14 speakers. Speaker ids cannot be compared across recordings or reruns.
- **Turn boundaries are plausible.** fa372ac7 (lang+diar): 146 turns, median 7 words / 2.5 s per turn, 20 one-word
  turns, 94% of turn changes fall on a word ending in `. ? ! ,`, median 0.3 s pause at a change. With `diar` alone:
  151 turns, 93% at punctuation. Sample (fa372ac7, 10 consecutive words, an ad voice handing off to the phone-number
  read):

  ```
  312.40-313.30  spk:0  Somos
  313.40-313.60  spk:0  el
  313.60-313.90  spk:0  grupo
  313.90-315.10  spk:0  internacional
  315.10-315.90  spk:0  Kayak.
  316.60-317.40  spk:1  Llámenos.
  317.60-318.20  spk:1  5
  318.20-318.90  spk:1  20
  318.90-319.30  spk:1  7
  319.30-320.50  spk:1  56
  ```

  The one Spanish talk file (6dab0a83) is the file with no labels, so a talk-show turn sample was not available.
- **Response shape.** Labels are `"spk:0"`, `"spk:1"`, ... (the docs show `spk_1`). With timestamps they sit on each
  `word_info` annotation as `speaker`; with diarization alone there is one annotation per turn. Nothing is written
  into the transcript text.

## Latency

Request time 54 to 56 s per 30 min file in every variant (wall 57 to 59 s with the upload). Diarization and
language hints add nothing measurable; differences are smaller than the spread between files (44 to 73 s, roughly
proportional to word count).

## Limits of this eval

- 6 files, one run per variant (two for baseline). The noise floor comes from one repeat, so it is itself rough.
- The reference is the production 2.5 Flash segment transcript, so "similarity" means agreement with production,
  and a better transcript of a hard window can score lower.
- Not measured: code-switched passages specifically (a language hint's main risk), and other Arabic locales
  (`ar-SA`, `ar-LB`) or multi-code lists such as `["es-US","en-US"]`.

## Spend

24 full-file calls (18 variants + 6 repeats) and probes: one discarded lang+diar run of 6dab0a83 (saved before raw
output was kept), 5/10/15/20/25 min cuts, four 20 s clips. About 826 audio minutes at $0.005/min, about $4.10. The
planned $3 plus $0.90 for the repeat and about $0.50 of diarization probes.
