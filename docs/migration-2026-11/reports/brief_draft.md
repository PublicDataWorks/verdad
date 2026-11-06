# Brief for the Paige Bailey call (Mon Nov 2, 10am PT)

## Where VERDAD stands

- Production Stage 1 has been down since Oct 24 00:25 UTC: Google's quota system rewrote the producer overrides on project 815787511264 (pdw-gemini) at 23:34 UTC on Oct 23 and re-applies them every 3 hours. gemini-2.5-flash went from 20,000 to 20 requests/day; 2.5-pro from 100 RPM / 15,000 RPD to 10 RPM / 2,000 RPD. The same caps were written onto paid tiers 2 and 3, so billing that project would not help.
- Vishal confirmed on Oct 30 that boosted free tiers are no longer permitted and offered credits on billing account verdad-billable (project verdad-factchecking, 371204627224). Amount and timing unknown.
- About 17,000 recordings are in Error (roughly 2,400 per day); nothing recorded after Oct 23 has been analyzed. Election day is Nov 3.

## What we measured this weekend (18 production recordings, 38 snippet clips)

Transcription with timestamps (the step that drives clip extraction):
- gemini-3.5-transcribe, word timestamps, one request per 30-minute file: 91.6 mean window similarity to the production transcript, timestamps verified by a shift test in Spanish, Arabic and English. About $0.15 and 52 s per file. Skips sung lyrics.
- Today's 20-second segment method on gemini-3.5-flash: 96.6 / 0.99 (7 files so far), $0.032 per file. On gemini-3.8-flash 93.1, $0.065. On gemini-3.5-flash-lite 88.8, $0.032.

Stage 1 detection (same transcripts, production prompt):
- Rerunning gemini-2.5-flash reproduces only 62% of its own production flags, so model-to-model differences below that are noise.
- Human-labelled snippets caught: 2.5 Flash 16/22; Gemma 4 31B PLACEHOLDER; Gemma 4 26B (Vertex MaaS) 12/22; 3.5 Flash Lite PLACEHOLDER by thinking level; 3.8 Flash PLACEHOLDER.

Stage 3 analysis (production prompt and tool loop):
- gemini-2.5-pro rerun: PLACEHOLDER. gemini-3.8-flash: PLACEHOLDER, but it runs more tool turns and resends the 30k-token prompt each turn, so it costs about $0.44 per snippet at list price. gemini-3.5-flash-lite: PLACEHOLDER.
- Context caching of the static prompt works on all three 3.x models (29.6k tokens cached) and is the main cost lever.

## Facts that shape the design

- Hosted Gemma 4 (31B and 26B) rejects audio input. Gemma can take the text stages (detection, restructuring, possibly Stage 3) but not transcription. Google's docs put native audio only on the E2B/E4B/12B sizes, which are not served on the API.
- Gemini 3.x rejects thinking_budget and needs thinking_level; 3.8 Flash also rejects minimal. The pipeline now handles this per model (PR #159).
- Per-day caps on a Tier 1 billed project: 3.5 Flash Lite 150,000 RPD, 3.5 Flash and 3.8 Flash 10,000 RPD, 3.5 Transcribe 100 RPD (10,000 at Tier 2). Gemma 4 free tier: 30 RPM, 14,400 RPD, 16k input tokens per minute.
- Vertex AI on verdad-435408 works today for gemini-3.5-flash-lite and Gemma 4 26B MaaS with no per-day caps; gemini-3.5-transcribe, 3.5 Flash and 3.8 Flash return 404 there for our project.

## Daily cost at measured usage (2,400 recordings, 18% reach timestamped transcription, 1,020 snippets to Stage 3), list prices

PLACEHOLDER table from cost_model.py

## Asks for Google

1. Confirm the credit amount and that it lands on verdad-billable; confirm Tier 2 on that project so 3.5 Transcribe is not capped at 100 requests/day.
2. Gemma 4 with audio: is a hosted audio-capable Gemma 4 (12B or a future Gemma 5) planned on the API? Today Gemma cannot replace the transcription stage.
3. Gemma 4 free-tier TPM: 16k input tokens per minute makes the 14k-token detection prompt one request per minute. A higher TPM, or a paid Gemma tier, would make Gemma viable for Stage 1 detection at volume.
4. Vertex access for gemini-3.5-transcribe and gemini-3.8-flash on project verdad-435408 (404 today), so transcription can run without per-day caps.
5. Review of the Stage 3 design: 170k to 520k prompt tokens per snippet because the 30k-token analysis prompt is resent on every tool turn. Caching, or the agentic video/audio understanding path Paige mentioned, could cut this several-fold.
6. If free-tier boosts exist for evaluators, VERDAD's eval harness and dataset are ready to run as a public benchmark for Gemma 4 / Gemma 5 on Spanish and Arabic radio.

## What happens next on our side

- PR #159 makes every model an env var and adds the 3.5 Transcribe path. Switching production is a Fly secret change plus one deploy; nothing is deployed yet.
- Once Rajiv says go: point processing-worker at a billed key, set STAGE1_* to the chosen models, re-queue the election-station backlog newest first (about 6,900 recordings), and watch cost per hour for the first day.
