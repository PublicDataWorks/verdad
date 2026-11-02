# Why Stage 1 transcription got complicated, and what each piece is for

Read-only research from git, Linear (VERDAD), Slack #verdad and docs/. Nothing was posted.

**Correction to the working theory.** The cause you named (unreliable long-audio timestamps) is right, but the design is not from 2026. Phong Nguyen built segment batching in Nov 2024 (VER-208) after Gemini 1.5 Flash gave bad timestamps on 30-minute audio. It was dropped in Oct 2025 as a "simplification", the same failure returned on Gemini 2.5 Flash in Nov 2025, and Quan Cao revived it on 27-28 Jan 2026 (VER-296). The untimed initial pass is an Oct 2024 cost gate (VER-80), removed Oct 2025 and re-enabled 2 Feb 2026. 2026 was a revival.

## A. Timeline

| Date | Change | Ref | Stated reason |
|---|---|---|---|
| 2024-10-14 | 1.5 Flash asked for start/end on raw 30-min audio returns 47:12 to 48:44 | Slack, Phong | "the generated timestamps remain unreliable, as they exceed 30 minutes." "We can not proceed Stage 2 Audio Clipping if the generated timestamps are unreliable." |
| 2024-10-14 to 17 | Whisper supplies the timestamped transcript; Gemini detects on it | VER-60/62/63, 5f82b0d | Rajiv: fall back to "Google Chirp or OpenAI Whisper" (Whisper credits existed). |
| 2024-10-25 | Cost-gated Stage 1: untimed Gemini transcript, initial detection, Whisper only if flagged | VER-80, 6491b48 | "reduce costs"; keep a transcript of every clip for audit. Phong: "Gemini fails to provide reliable timestamps, its transcription quality is not so bad." |
| 2024-10-30/31 | Clip context 90 s before, 30 s after (was 30/30 since 10-11) | a475ee2, c309f1f | Rajiv: "the chance to hear more (90 sec) of the surrounding context." Phong: 90 s "could possible include other snippets." |
| 2024-11-02 / 11-14 | Stage 2 checks start<=end, then end<=audio duration | 77cd133, 6ffb788 | Guard against LLM-emitted times. |
| 2024-11-14/15 | Google's diarization suggestion fails | Slack | Phong: "The generated timestamps are incorrect," even with the raw transcript attached. |
| 2024-11-20 | Phong's method: cut into 5 s segments, transcribe each alone | Slack | "our approach works!" but about 40 min per file. |
| 2024-11-22 | Shipped with 10 s segments, `<Segment N>` tags, JSON | VER-208, 44caec5 | Replace Whisper with something cheaper that still has reliable times. VER-209 had planned around an "8192-token output limit" on one 30-min request. |
| 2024-11-25 | Whisper replaced by Gemini segment generator | VER-210, 4725f2b | Cost. |
| 2024-11-27/28 | `regenerate_timestamped_transcript` flow | VER-222, 26baf29 | Re-time stored responses without redoing detection. |
| 2024-12-02 | Context after raised 30 s to 60 s | 3d9c3c1 | Phong: "the timestamp offset may exceed 10 seconds, causing the snippet to fall outside the [-90 : snippet : +30] range." |
| 2024-12-12 | Gemini 1206 whole-file, falling back to the segment generator on 429 | VER-252, 35fed08 | Cheaper first choice, reliable fallback. |
| 2025-10-24 | Initial pass and initial detection removed; one whole-file timestamped call on Flash | 1c01071 | "Simplify transcription and detection logic." No incident cited. |
| 2025-11-11 | Quan finds Flash timestamps wrong | Slack | "erroneous audio clipping and snippet extraction." Example: `10:50` then `1:00` where `11:00` was meant. VER-284 (validate start/end) filed; still an empty Todo. |
| 2025-11-12 | Pro tested about 10 times | Slack, Quan | 10-min and 30-min: "All timestamps are correct across all attempts." Not adopted: Pro/Whisper "costly ... would quickly exhaust the quota." |
| 2026-01-22 | Quan: top issue; back to segments | Slack | "mismatched timestamp transcription ... extract wrong audio clips." Phong: "Gemini model detects timestamps more accurately when processing shorter audio clips." |
| 2026-01-27/28 | Segments revived: 30 s x 20/request, same day 20 s x 30/request; response, count and range validation | VER-296, 321a8a7, 89240f4, 2c80f55, 46c39fb | "improved transcription accuracy and processing efficiency." |
| 2026-02-02 | Initial pass and detection re-enabled | 8163a06 | Commit gives no reason. Gemini meeting notes (1 Feb): "re-enabled the pre-process transcription step to improve accuracy by splitting audio into segments when misinformation is detected, as Gemini Flash alone was insufficient." |
| 2026-02-09 | 10 s fallback generator deleted | 2639987 | Unused. |
| 2026-03-16 | KB context built from the initial transcript | 8c93b6a | New consumer of the untimed pass. |
| 2026-09-30 | Audio-file retry sweep | VER-417 | 503/429 errors. |
| 2026-10-24 on | 2.5 quota cut from 20,000 to 20/day; Stage 1 down | VER-438, VER-441 | Google removed the boosted free tier. |
| 2026-10-30 | `gemini-3.5-transcribe` path emits the same 20 s `[MM:SS]` lines | PR #159, 431aca1 | Keeps Stage 2 and the detection prompt untouched. |

## B. Failure modes with direct long-audio transcription

1. **Impossible times (1.5 Flash, Oct 2024):** stamps past the clip length (47:12 in a 30-min file); extra seconds/token counters in the schema did not help.
2. **Prompting does not fix it (Nov 2024):** the diarization route failed.
3. **Digit truncation (2.5 Flash, Nov 2025):** `10:50` then `1:00`. Lawrence Sinclair suggested truncation and a monotonic-sequence check as a cheap detector. This is the only concrete 2.5 Flash example in the record.
4. **Output length:** `MAX_TOKENS` handling is still in the executors. VER-417 counts 85 "too long" errors among 1,069 Stage 1 errors in 7 days to 30 Sep 2026, but does not say which call.
5. **Segment-count mismatch** (the workaround's own failure): 34 of those 1,069. VER-417 excludes "too long" and mismatch from the retry sweep.
6. **Pro was accurate, Flash was not.** Quan's 10-run Pro test is the only quantified accuracy evidence. Cost and quota ruled it out.
7. **Cost of the workaround:** about 40 min per file at 5 s segments (2024); now about 90 inline 20 s clips per file.
8. **Not timestamp issues:** 503 (367), 429 (265), `NoneType` (193), "No response" (107), and the Oct 2026 quota cut.

**Gap:** nothing measures a 2.5 Flash timestamp error rate or offset size. "Drift" as a cumulative offset is not documented anywhere; the observed failures are impossible or truncated stamps.

## C. What exists only because of timestamp failures vs other purposes

**Delete candidates if word timestamps are trusted:**
- `GeminiTimestampTranscriptionGenerator`, `split_audio_into_segments` (pydub), `<Segment N>` wrapping, `segment_length=20`, `batch_size=30` (executors.py, tasks.py).
- The "Segment count mismatch" check and segment-number range check (2c80f55).
- The `timestamped_transcription` prompt set in `prompt_versions` (the `transcribe` path already ignores it).
- The 20 s `[MM:SS]` synthetic format. It exists to make index-derived stamps look like a transcript, and it quantizes boundaries to 20 s. PR #159 keeps it only to avoid touching Stage 2 and the detection prompt.
- `transcribe_audio_file_with_open_ai_whisper_1` and its export in `stage_1/__init__.py`: dead since Nov 2024; grep callers first.
- `regenerate_timestamped_transcript` (VER-222): keep only if re-timing old rows is still wanted.

**Padding that partly covers imprecise boundaries:** the 60 s "after" was added for "timestamp offset may exceed 10 seconds". The 90 s "before" was an editorial context request, not a timestamp fix.

**Serve another purpose, keep or decide on purpose:**
- **Untimed initial pass + initial detection.** Original role is the cost gate: about 80% of recordings produce no flags (Thien, 24 Sep 2026), so they never pay for the timed pass. It is also the stored transcript of every recording (audit, search, the VER-430 Texas re-read) and the input to `fetch_kb_context`. My arithmetic from VER-438/441 figures: 3.5-transcribe at about $0.15/file on about 2,400 files/day is about $360/day on every file, versus about $0.03/file for the flash-lite segment route; 3.5 Transcribe is 100 requests/day at Tier 1 and 10,000 at Tier 2. The gate is hard to remove.
- Retries and the VER-417 sweep: 429/503, unrelated to timestamps.
- Stage 2 range/ordering checks and the detection prompt's start<=end rule: protect against any bad LLM time, including main detection's.
- The 1,799 s cap in the `transcribe` path: an API limit, not an accuracy workaround.

## D. Clip-boundary constraints a redesign must keep

- **Context:** clip is 90 s before the snippet start to 60 s after its end, clamped to the audio (`stage_2/tasks.py`, defaults in `main.py`). Journalists asked for the lead-in.
- **Stage 3 reads the clip.** Rajiv saw the AI title and summary change between 30 s and 90 s lead-in (31 Oct 2024), so padding changes are an analysis change; evaluate them.
- **Stored semantics:** `snippets.start_time`/`end_time` are positions inside the clip (original start minus lead-in), as MM:SS. The frontend `AudioPlayer` and `SnippetAudioPlayer` seek to `start_time` on load (VER-119); `end_time` is stored but not used for playback.
- **Stage 2 hard-fails** if `end_time` exceeds the audio duration or start>end, which errors the whole response. A word-timestamp design should clamp instead.
- **Window contract:** main detection reads one `[MM:SS]` line per 20 s and emits MM:SS, with examples in the prompt (05:30, 07:15). Finer inputs mean changing the prompt, examples and schema together.
- **Persisted fields:** `stage_1_llm_responses.transcriptor` (model id), `timestamped_transcription`, prompt-version ids; reruns key off them.
- **Overlap:** Phong's 2024 concern that 90 s could capture neighboring snippets was never addressed.

## E. Open questions

1. What was the real 2.5 Flash timestamp failure rate? Nothing quantifies it; VER-284 is empty.
2. Did the Jan 2026 segment fix measurably help? No post-deploy measurement found. PR #159's eval (91.6 mean window similarity, 95% of windows above 70) compares 3.5 Transcribe with the segment output, not with ground truth. The shifted-by-20 s control (similarity about 48) is the best evidence the timestamps are real.
3. Is main detection's own start/end emission reliable once the input is right? It is a separate LLM step, and I found no validation of it (VER-284 is empty).
4. Should the 60 s "after" shrink with word timestamps, or stay for context?
5. Keep the untimed pass for cost and archive, or move it to a cheaper model while 3.5 Transcribe handles flagged files only (current design)?
6. 3.5 Transcribe skips sung lyrics (VER-438 comment). Does that lose jingles and ads (the Oct 2024 Kari Lake ad example)?
7. One failed 3.5 Transcribe call now fails a whole 30-min file, where batching failed 30 windows at a time. Is per-file retry cost acceptable?
8. The frontend parses `start_time` as h:m:s. I did not check how the DB column turns "MM:SS" into that; confirm before any format change.

Linear read: VER-60, 62, 63, 80, 100, 208, 209, 210, 215, 222, 252, 284, 296, 417, 438, 441. Slack threads: 2024-10-14, 10-20, 10-29, 11-14, 11-20, 11-22, 12-02, 2025-11-11, 12-17, 2026-01-21, 02-01.
