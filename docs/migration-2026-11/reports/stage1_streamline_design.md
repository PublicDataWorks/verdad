# Stage 1 streamlined around gemini-3.5-transcribe (design draft, 2026-10-31)

## Today (per recording)

1. Upload the whole 30-min mp3 to Gemini (Files API) and ask 2.5 Flash for an untimed transcript. 1 audio call, ~58k audio tokens.
2. KB context retrieval (OpenAI embeddings) on that transcript.
3. Initial detection (text, 2.5 Flash, ~12k tokens). If nothing flagged: done (82% of recordings).
4. Otherwise: pydub splits the mp3 into 90 x 20 s clips, re-encodes each, sends 3 requests of 30 inline clips to 2.5 Flash, requires exactly 30 transcripts back per request, stamps `[MM:SS]` from the clip index. 3 audio calls (~19k tokens each), plus retries on "segment count mismatch".
5. Main detection (text, 2.5 Flash, ~14k tokens) on the stamped transcript, output start/end in MM:SS at 20 s granularity.
6. Stage 2 clips with 90 s before and 60 s after.

Audio is transcribed twice for 18% of recordings, and the timestamp is a clip index, not a measurement.

## Proposed (per recording)

1. One `gemini-3.5-transcribe` request per recording with word timestamps (interactions endpoint). Output: words with start/end seconds.
   Derive two views without another model call: (a) the plain transcript (concatenated words, speaker turns if diarization is on) for KB retrieval and detection; (b) the windowed `[MM:SS]` transcript at 20 s for compatibility with the detection prompt and Stage 2, and keep the word list in `timestamped_transcription` JSON (new key `words`) so Stage 2 can cut at word boundaries later.
2. KB context retrieval as today.
3. Detection: two options behind a flag.
   - `two_pass` (today's shape): initial detection on the plain transcript, main detection on the windowed transcript only when flagged. Keeps outcomes comparable; the second pass costs only text tokens now.
   - `single_pass`: one detection on the windowed transcript (main-detection prompt) for every recording. One fewer LLM call per flagged file, one more text call per unflagged file. With Gemma 4 free or 3.5 Flash Lite at $0.011 that is cheap; worth an A/B before switching.
4. Stage 2 unchanged at first (MM:SS + padding). Follow-up: snap clip boundaries to the word timestamps (start of the first flagged word minus a shorter context, end of the last word plus a shorter tail) and store exact seconds; that would shrink clips and remove most of the 150 s of padding.

What gets deleted when the flag is on: pydub segment splitting and the 90 temp files, the 30-clip batch request and its count check, the whole-file upload to a chat model, the `thinking_budget` audio calls, `regenerate_timestamped_transcript` reruns for mismatch errors. What stays: Files API upload of the mp3 for Transcribe (one upload), retries on 429/5xx, the trim to 1799 s, Stage 2.

## Failure handling

- Transcribe returned no word timestamps or a non-`completed` status: fail the file (Error) with a clear message; do not fall back to index stamping silently. Optional: fall back to the segment method behind `STAGE1_TRANSCRIPTION_FALLBACK=segments`.
- Sung lyrics are skipped by the model: acceptable for talk radio; log the share of empty windows per file so music-heavy stations are visible.
- 30-minute cap with timestamps: recordings are 30:00; trim to 1799 s (already in the branch). Longer recordings would need chunking at a silence boundary; not needed today.
- Quota: Tier 1 is 100 RPD; the flow must not be switched on in production before Tier 2 or a raise.

## Cost and quota (measured)

- Today's volume 2,430 files/day: one request each = 2,430 RPD, 109M input tokens/day, $365/day at list. Removes ~$46/day of 2.5 Flash untimed passes and ~$20/day of segment passes, so the net increase is about $300/day for timestamps on every recording and a much simpler flow. The gated variant (Transcribe only for the 18% flagged) costs about $66/day but keeps the double pass.

## Implementation plan (on top of PR #159)

1. `transcribe_executor.py`: return a structured result `{plain_text, windows, words, duration_s}` in addition to the `[MM:SS]` string; persist `words` into `stage_1_llm_responses.timestamped_transcription` JSON (jsonb column already exists; no migration).
2. `stage_1/tasks.py::process_audio_file`: when `STAGE1_TRANSCRIPTION_METHOD=transcribe`, call Transcribe first and reuse its plain text as `initial_transcription`; skip `Stage1PreprocessTranscriptionExecutor`. Add `STAGE1_DETECTION_PASSES=two|one`.
3. Tests: mock the interactions response; assert one audio call per recording, both views derived, `transcriptor` recorded, detection pass count per flag.
4. Eval: rerun the 18-file set end to end with the new flow against today's outputs (flag agreement, human-label hits) before enabling in production.
5. Later PR: word-boundary clipping in Stage 2.
