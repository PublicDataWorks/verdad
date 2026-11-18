# Cloudflare Workers AI for VERDAD: economics and effectiveness

Prepared 2026-11-01. Pricing and catalog pulled from developers.cloudflare.com on 2026-11-01 (pricing page "Last updated Oct 20, 2026"; limits page "Last updated Sep 17, 2026").

**Interpretation.** Rajiv wrote "paid Jev-based models". This report reads that as Cloudflare Workers AI's paid, Cloudflare-hosted open-weight models (Gemma, Llama, Qwen, Mistral, DeepSeek, GLM, Whisper, embedding models) plus the Deepgram partner speech models served on Workers AI. If something else was meant, the catalog and pricing tables below still apply.

## Verdict

Cloudflare cannot replace the Gemini pipeline, but two stages are worth a trial. **Stage 1 transcription** is the only place with real money: Whisper large-v3-turbo on Workers AI costs about **$37/day** for all 2,430 recordings versus **$365/day** for gemini-3.5-transcribe (Phase 2) or $80 to $158/day for Phase 1, and it returns word-level timestamps. The risk is quality: published Arabic WER for the turbo model is weak (33% average across dialect sets), Whisper hallucinates on music and silence, and long files must be chunked. **Stage 1 detection** is the safest win: Cloudflare hosts exactly the Gemma 4 26B-A4B we already evaluated on Vertex (14 to 15/22 human-labelled hits with the v4 prompt, versus 16/22 for 3.8 Flash@low), at about **$3.30 to $3.90/day** versus $28 to $49/day on 3.8 Flash, with a 300 requests/minute limit instead of the Gemini API's free-tier 429s. Stage 3 has cheap tool-calling models with prefix caching (GLM-5.3-Flash, DeepSeek-V4.1-Flash at roughly $30 to $36/day cached), but no evidence they meet the fact-checking bar, and the paid-tier ones are capped at 20 requests/minute. **Embeddings, the expected easy win, are not one**: the whole Stage 5 bill is about $0.40/day, so bge-m3 saves under $0.40/day while forcing a vector(3072) to vector(1024) migration and a full re-embed. No live probe ran: there is no Cloudflare token in the environment and wrangler is not logged in.

## Per-stage summary

Volumes: 2,430 recordings/day (72,900 audio minutes), 1,020 Stage 3 clips/day. Google figures are the ones given in the brief or measured in our Oct 30 to 31 evals. Cloudflare figures use the published per-unit prices and our measured token counts (details in the arithmetic section).

| Stage | Google pick | Google $/day (1x / 10x) | Best Cloudflare option | CF $/day (1x / 10x) | Quality verdict | Blockers |
|---|---|---|---|---|---|---|
| 1. Transcription with timestamps | gemini-3.5-transcribe, $0.15/file (Phase 2); Phase 1 3.5/3.8 Flash on 20 s segments | 364.50 / 3,645 (Phase 2); 80 to 158 / 802 to 1,580 (Phase 1) | `@cf/openai/whisper-large-v3-turbo`, $0.0005/min | 36.45 to 37.40 / 365 to 374 | Spanish likely fine; Arabic unproven and probably below our 83 to 90 bar; hallucination risk on music | Must chunk 30-min files (no documented size cap, CF's own tutorial uses 1 MB chunks); word times come from Whisper alignment, not a dedicated aligner; turbo is the only large Whisper offered |
| 1. Transcription (alt) | same | same | `@cf/deepgram/nova-3`, $0.0052/min | 379.08 / 3,791 | Lists Arabic dialect codes and Spanish; no eval | Costs the same as gemini-3.5-transcribe, so no saving |
| 1. Detection (text, JSON) | gemini-3.8-flash@low (gemma-4-31b free but quota-capped) | 27.57 (measured v4) to 48.60 (brief) / 276 to 486 | `@cf/google/gemma-4-26b-a4b-it`, $0.10 in / $0.30 out per M | 3.29 (v4) to 3.92 (prod prompt) / 33 to 39 | Same model scored 14 to 15/22 on Vertex vs 16/22 for 3.8 Flash; adds a few false flags | JSON schema not guaranteed (error path must be handled); CF quantization unknown, so re-verify recall; no 31B on CF |
| 3. Analysis (tool loop, 30k prompt) | gemini-3.8-flash, $0.46/clip uncached | 468 uncached, ~234 with caching / 2,341 to 4,682 | `@cf/zai-org/glm-5.3-flash` or `@cf/deepseek-ai/deepseek-v4.1-flash-1017` (prefix caching) | 30 to 36 at 90% cache hit, 90 to 183 uncached / 302 to 1,832 | Unknown; no Spanish/Arabic fact-check eval; Stage 4 already shows Gemini fabricating citations, weaker models are a risk | Both are "paid models": 20 req/min per model (50 with AI Gateway credits), which our loop exceeds above ~2x volume; cache hits depend on `x-session-affinity` routing |
| 4. Review (ADK agents) | gemini-3.8-flash via Google ADK | not measured | none recommended | not estimated | Not evaluated | `agents.py` builds `Gemini(...)` model objects; swapping needs ADK's LiteLLM path and a new eval |
| 5. Embeddings | OpenAI text-embedding-3-large (3072 dims); planned gemini-embedding-2 | ~0.40 / ~4 (est., 3k tokens/snippet) | `@cf/baai/bge-m3` (1024 dims, $0.012/M) | ~0.04 / ~0.37 | bge-m3 is strong on multilingual retrieval (see evidence) | Saving is under $0.40/day; requires schema change from vector(3072), re-embedding the corpus, and changing the Stage 4 KB search (`stage_4/tools.py` also calls text-embedding-3-large) |

## Workers AI catalog and pricing (relevant models)

Source for all prices: [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) (updated Oct 20, 2026). Workers AI bills in Neurons at **$0.011 per 1,000 Neurons** beyond a free 10,000 Neurons/day (about $0.11/day of free usage); every model now also shows an equivalent per-token or per-minute price, which is what the tables use. Context windows and capability flags come from each model page at `https://developers.cloudflare.com/workers-ai/models/<model>/`. Rate limits come from [Workers AI limits](https://developers.cloudflare.com/workers-ai/platform/limits/). Workers AI is GA; the limits page notes beta models may get lower limits. "Paid model" below means the model requires a paid billing method and gets the 20/50 req/min limit instead of the task default.

### Speech recognition

| Model | Price | Neurons | Timestamps | Languages | Rate limit | Notes |
|---|---|---|---|---|---|---|
| `@cf/openai/whisper-large-v3-turbo` | $0.0005/audio min (model page: $0.000513) | 46.63/min | Yes: `segments[].words[]` with `start`/`end` (output schema) | Whisper multilingual, `language` hint | ASR 720 req/min | Params include `vad_filter`, `initial_prompt`, `condition_on_previous_text`, `hallucination_silence_threshold`, `beam_size`. Batch supported. No documented per-request size/duration limit; CF's [chunking tutorial](https://developers.cloudflare.com/workers-ai/guides/tutorials/build-a-workers-ai-whisper-with-chunking/) splits into 1 MB chunks "to overcome memory and execution time limitations". |
| `@cf/openai/whisper` | $0.0005/min (model page: $0.000453) | 41.14/min | Yes: top-level `words[]` | Multilingual | 720 req/min | Size/version not stated; no tuning params. |
| `@cf/openai/whisper-tiny-en` | n/a | n/a | n/a | English only | | Not usable. |
| `@cf/deepgram/nova-3` (partner) | $0.0052/min HTTP, $0.0092/min WebSocket | 472.73/min | Yes: words with start/end | Deepgram lists Spanish (`es`, `es-419`) and Arabic (`ar`, `ar-EG`, `ar-SA`, `ar-IQ`, `ar-MA`, and more) per [Deepgram languages](https://developers.deepgram.com/docs/models-languages-overview); CF says "only certain languages are available" depending on endpoint | 720 req/min | Diarization, keyterm prompting, topics. Not verified that every Deepgram language is enabled on the CF-hosted endpoint. |
| `@cf/deepgram/flux` | $0.0077/min (WebSocket) | 700/min | | | | Conversational/voice-agent model, not for batch. |

There is no non-turbo whisper-large-v3, no Gemma audio model (Gemma 4 audio exists only on the small E2B/E4B sizes, which CF does not host), and no ElevenLabs model on Workers AI. Deepgram Aura (TTS) is irrelevant here.

### Text generation (candidates for detection, analysis, review)

| Model | $/M in | $/M cached in | $/M out | Context | Function calling | Reasoning | Batch | Paid model | Notes |
|---|---|---|---|---|---|---|---|---|---|
| `@cf/google/gemma-4-26b-a4b-it` | 0.10 | n/a | 0.30 | 256,000 | Yes | Yes | Yes | No (300 req/min) | Only Gemma 4 size on CF. No 31B. Accepts `response_format`. |
| `@cf/zai-org/glm-5.3-flash` | 0.15 | 0.03 | 0.50 | 1,048,576 | Yes | low/high/max (default max) | No | Yes (20/50 req/min) | Cheapest long-context model with cache pricing. |
| `@cf/deepseek-ai/deepseek-v4.1-flash-1017` | 0.30 | 0.006 | 1.20 | 1,048,576 | Yes | none/low/high/max | No | Yes | Very cheap cached input. |
| `@cf/deepseek-ai/deepseek-v4-flash-0731` | 0.44 | 0.014 | 1.32 | 1,048,576 | Yes | none/low/high/max | Yes | Yes | |
| `@cf/deepseek-ai/deepseek-v4-pro-0813` | 1.32 | 0.044 | 3.96 | 1M (per catalog) | Yes | Yes | | Yes | |
| `@cf/qwen/qwen3.8-27b` | 0.45 | 0.05 | 3.20 | 262,144 | Yes | low/medium/xhigh | Yes | No | Expensive output. |
| `@cf/qwen/qwen3-30b-a3b-fp8` | 0.051 | n/a | 0.335 | 32,768 | Yes | Yes | Yes | No | Context too small for Stage 3; tight for detection. |
| `@cf/openai/gpt-oss-120b` | 0.35 | n/a | 0.75 | 128,000 | Yes | low/medium/high | Yes | No | |
| `@cf/openai/gpt-oss-20b` | 0.20 | n/a | 0.30 | (not checked) | | | | No | |
| `@cf/meta/llama-4-scout-17b-16e-instruct` | 0.27 | n/a | 0.85 | 131,000 | Yes | No | Yes | No | |
| `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 0.293 | n/a | 2.253 | 24,000 | Yes | No | Yes | No | Context too small for a 14k prompt plus long transcripts; officially listed for JSON mode. |
| `@cf/mistralai/mistral-small-3.1-24b-instruct` | 0.351 | n/a | 0.555 | 128,000 | Yes | No | No | No | |
| `@cf/nvidia/nemotron-3-120b-a12b` | 0.50 | n/a | 1.50 | 256,000 | Yes | Yes | No | No | |
| `@cf/moonshotai/kimi-k2.6` | 0.95 | 0.16 | 4.00 | 262,100 | Yes | | | Yes | Pricier than 2.5 Pro once output is counted. |
| `@cf/zai-org/glm-4.7-flash` | 0.06 | n/a | 0.40 | 131,072 | Yes | Yes | No | No | "100+ languages". |
| `@cf/aisingapore/gemma-sea-lion-v4-27b-it` | 0.351 | n/a | 0.555 | 128,000 | not listed | | | No | SE-Asian tuned Gemma. |
| Also listed | | | | | | | | | Llama 3.1/3.2 small models, Mistral 7B, QwQ-32B, Qwen2.5-coder, DeepSeek-R1-distill-32B, Granite 4.0 micro, EuroLLM 9B, Apertus 8B (form access), GLM-5.2/5.3. `gemma-3-12b-it` and `kimi-k2.5` still appear on the pricing page but their model pages return 404. |

Max output tokens are not stated on the model pages; requests take `max_completion_tokens`.

**Structured output.** [JSON Mode](https://developers.cloudflare.com/workers-ai/features/json-mode/) accepts OpenAI-style `response_format` with `json_schema`. The officially listed models are older ones (Llama 3.x 8B/70B, Hermes 2 Pro, DeepSeek-R1-distill); newer models such as Gemma 4 expose `response_format` in their input schema. Cloudflare says it "can't guarantee that the model responds according to the requested JSON Schema" and returns `JSON Mode couldn't be met` in that case; JSON mode does not stream. We would keep pydantic validation and a retry, as we do for Gemini.

**Prompt caching.** [Prefix caching](https://developers.cloudflare.com/workers-ai/features/prompt-caching/) is on by default for select models, billed at the cached rate shown on the model page, and only hits when requests land on the same instance, which the `x-session-affinity` header encourages. Gemma 4 26B has no cached price, so its 14k detection prompt is billed in full each time (it is cheap enough that this does not matter).

**Rate limits.** Text generation 300 req/min per model unless it is a paid model (20 req/min standard, 50 with prepaid AI Gateway credits); ASR 720 req/min; embeddings 3,000 req/min. The [Batch API](https://developers.cloudflare.com/workers-ai/features/batch-api/) queues requests with a guarantee of eventual completion, 10 MB total payload per batch. Higher limits need the custom requirements form.

### Embeddings

| Model | $/M tokens | Context | Dims | Notes |
|---|---|---|---|---|
| `@cf/baai/bge-m3` | 0.012 (page: 0.0118) | 60,000 | 1024 | Multilingual dense + sparse + multi-vector; Batch supported. |
| `@cf/qwen/qwen3-embedding-0.6b` | 0.012 | 8,192 | 1024 (model default) | Multilingual. |
| `@cf/google/embeddinggemma-300m` | not on pricing page | | 768 (model default) | Beta; 100+ languages. |
| `@cf/baai/bge-large-en-v1.5` | 0.204 | | 1024 | English only. |
| `@cf/pfnet/plamo-embedding-1b` | 0.019 | | | Japanese. |

No Workers AI embedding model produces 3072 dimensions, so any switch is a schema migration.

## Arithmetic

All per-day figures: per-unit price times daily volume, then times 1, 2, 5, 10.

### Stage 1 transcription (72,900 audio min/day)

| Option | Unit cost | 1x | 2x | 5x | 10x |
|---|---|---|---|---|---|
| gemini-3.5-transcribe (Phase 2) | $0.15/file x 2,430 | $364.50 | $729.00 | $1,822.50 | $3,645.00 |
| Gemini Phase 1, 20 s segments | $0.033 to $0.065/file | $80 to $158 | $160 to $316 | $401 to $790 | $802 to $1,580 |
| CF whisper-large-v3-turbo | 72,900 x $0.0005 (or $0.000513) | $36.45 to $37.40 | $72.90 to $74.80 | $182 to $187 | $365 to $374 |
| CF nova-3 (HTTP) | 72,900 x $0.0052 | $379.08 | $758.16 | $1,895.40 | $3,790.80 |
| Hybrid: Whisper on all, 3.5-transcribe on the 39% that pass detection | $37.40 + 0.39 x $364.50 | $179.55 | $359.11 | $897.76 | $1,795.53 |

Neuron check: 46.63 neurons/min x 30 min = 1,399 neurons/file = $0.0154/file. Our eval mp3s are 14.4 MB per 30 minutes (64 kbps), so 1 MB chunks are about 2 minutes, about 14 requests/file, about 34,000 requests/day (24/min average, 236/min at 10x, under the 720/min ASR limit). Calling the REST API from the Fly workers needs no Worker, so there is no Workers request charge.

### Stage 1 detection (2,430 recordings/day)

Measured tokens from `eval/results_detection/gemma-4-26b-a4b-it-maas*` (Vertex, same model): v4 prompt 11,239 in / 770 out; production prompt 14,089 in / 675 out; no thinking tokens.

- v4: 11,239 x $0.10/M + 770 x $0.30/M = $0.001124 + $0.000231 = **$0.00135/file** (123 neurons). x 2,430 = **$3.29/day**.
- prod prompt: 14,089 x $0.10/M + 675 x $0.30/M = **$0.00161/file**, **$3.92/day**.
- Google: 3.8 Flash@low v4 measured $0.01134/file = $27.57/day; brief's $0.02/file = $48.60/day.

| Option | 1x | 2x | 5x | 10x |
|---|---|---|---|---|
| 3.8 Flash@low (measured v4 to brief) | $27.57 to $48.60 | $55 to $97 | $138 to $243 | $276 to $486 |
| CF gemma-4-26b (v4 to prod prompt) | $3.29 to $3.92 | $6.58 to $7.83 | $16.46 to $19.58 | $32.92 to $39.16 |

Throughput: 2,430/day is 1.7 req/min; 10x is 17 req/min against a 300 req/min limit.

### Stage 3 analysis (1,020 clips/day)

Measured 3.8 Flash usage per clip (`eval/results_stage3/gemini-3.8-flash`, n=36): 545,329 cumulative prompt tokens across the tool loop, 6,277 output + 7,063 thinking = 13,340 billed output. Check: 545,329 x $0.75/M + 13,340 x $3.75/M = $0.459/clip, matching the $0.46 in the brief. The CF rows reuse that token profile, which is an assumption: other models take different numbers of turns and think more or less. "90% cached" assumes 90% of the cumulative prompt is a repeated prefix that hits the cache.

| Option | $/clip uncached | $/clip 90% cached | 1x (cached) | 2x | 5x | 10x |
|---|---|---|---|---|---|---|
| gemini-3.8-flash | $0.459 | ~$0.23 (brief: caching about halves it) | $234 (uncached $468) | $468 | $1,171 | $2,341 |
| gemini-2.5-pro (brief) | $0.29 | | $296 | $592 | $1,479 | $2,958 |
| CF glm-5.3-flash | $0.0885 | $0.0296 | $30.17 (uncached $90) | $60 | $151 | $302 |
| CF deepseek-v4.1-flash | $0.1796 | $0.0353 | $36.02 (uncached $183) | $72 | $180 | $360 |
| CF gemma-4-26b (no cache price) | $0.0585 | $0.0585 | $59.71 | $119 | $299 | $597 |
| CF qwen3.8-27b | $0.2881 | $0.0918 | $93.60 | $187 | $468 | $936 |
| CF gpt-oss-120b (no cache price) | $0.2009 | $0.2009 | $204.89 | $410 | $1,024 | $2,049 |
| CF kimi-k2.6 | $0.5714 | $0.1837 | $187.37 | $375 | $937 | $1,874 |

Rate limit check for paid models (GLM-5.3-Flash, DeepSeek): if a clip takes about 12 model turns (545k cumulative input at about 45k per turn; an estimate, the harness does not log turns), 1,020 clips is about 12,240 requests/day, 8.5/min on average. That fits 20/min at 1x only if the load is spread evenly; at 5x (42/min) it needs the 50/min credit tier and at 10x (85/min) it exceeds both. Gemma 4, Qwen3.8 and gpt-oss get 300/min.

### Stage 5 embeddings (1,020 snippets/day)

Assumes about 3,000 tokens per snippet document (not measured here; `snippet_embeddings.document_token_count` in production has the real number, not queried per instructions). Even at the 8,192-token cap the OpenAI bill is $1.06/day.

| Option | 1x | 2x | 5x | 10x |
|---|---|---|---|---|
| OpenAI text-embedding-3-large ($0.13/M) | $0.40 | $0.80 | $1.99 | $3.98 |
| CF bge-m3 ($0.012/M) | $0.04 | $0.07 | $0.18 | $0.37 |

### Platform overheads

- Workers Paid plan: $5/month minimum ([Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)), needed above the 10,000-neuron free tier. Worker requests ($0.30/M beyond 10M/month) only apply if we put a Worker in the path; calling the Workers AI REST API from Fly does not.
- AI Gateway core features (analytics, caching, rate limiting) are free; prepaid Unified Billing credits carry a 5% fee ([AI Gateway pricing](https://developers.cloudflare.com/ai-gateway/reference/pricing/)).
- Free neuron allocation is worth about $0.11/day and does not change any conclusion.

## Effectiveness and evidence

**Transcription.** Our bar is window similarity against production transcripts: 91.6 overall, 83 to 90 for Arabic, for gemini-3.5-transcribe. There is no Whisper run in our harness yet. Published evidence:
- Open Universal Arabic ASR Leaderboard ([arXiv 2412.13788](https://arxiv.org/html/2412.13788v1), Table 1): whisper-large-v3-turbo averages **33.3% WER** across five Arabic test sets (SADA 60.4%, Common Voice 18 25.7%, MASC clean 25.5%, MASC noisy 37.2%, MGB-2 17.8%), worse than whisper-large-v3 (29.9%) and NVIDIA's Arabic Conformer (25.7%). Dialectal and noisy broadcast audio is where it is weakest, which is most of our Arabic stations.
- Spanish is one of Whisper's best-resourced languages; secondary sources put turbo within about 0.5 to 2 points of large-v3 on Spanish and 2 to 4 points behind on Arabic ([Vexascribe summary](https://vexascribe.com/whisper-large-v3-vs-turbo), which cites the Whisper paper's FLEURS tables; treat as approximate).
- Hallucination: "Careless Whisper" ([arXiv 2402.08021](https://arxiv.org/abs/2402.08021v1), FAccT 2024) found Whisper inventing text in about 1.4% of segments, 38% of which contained harmful content, concentrated in pauses and non-speech. Radio has music beds, jingles and ads. For a disinformation product, invented speech is a correctness problem, not just noise; `vad_filter`, `hallucination_silence_threshold` and `condition_on_previous_text=false` help but must be measured.
- Timestamps: word times exist in the output schema. Whisper's word timing comes from attention alignment and is typically good to a few hundred milliseconds, adequate for Stage 2 clipping with padding (`STAGE2_USE_WORD_TIMES`). Chunk boundaries must be offset and stitched; splitting on silence with ffmpeg avoids cutting words.

**Detection.** The strongest evidence of the whole report, because we already ran the exact model: Gemma 4 26B-A4B on Vertex MaaS scored 12, 14, 10/22 with the production prompt and 15, 14/22 with v4, at 2.9 to 3.6 flags/file and precision-at-production 0.91 to 0.94 (`reports/prompt_tuning.md`). 3.8 Flash@low v4 scored 16/22 twice; Gemma 31B 11 to 12/13 on 6 files. So 26B is one to two hits behind 3.8 Flash and adds some false flags (deportation law-firm ad, "free love doesn't exist"), which Stage 3 is designed to filter. Caveat: Cloudflare does not state the quantization for Gemma 4 26B; recall must be re-measured on CF before relying on Vertex numbers. Google's model card puts 26B-A4B about 2 points below 31B on multilingual MMMLU (86.3 vs 88.4, as reported by third-party comparisons of the [Gemma 4 card](https://deepmind.google/models/gemma/gemma-4/); not verified against the card itself).

**Analysis (Stage 3).** Stage 3's tools are our own functions (`searxng_web_search`, `web_url_read`, `jina_web_search` in `stage_3/executors.py`) declared as Gemini `FunctionDeclaration`s, so the loop is portable to OpenAI-style tool calling on Workers AI; nothing depends on Google Search grounding. Capability exists on paper (1M context, function calling, cached input). What is missing is any evidence on our task: grounded fact-checking in Spanish and Arabic, citing only what the tools returned, and filling a large response schema. Given that Stage 4 already shows Gemini inventing fact-check URLs when searches come back empty, a cheaper model failing quietly is the main risk. This is a candidate for a small spike, not a migration.

**Review (Stage 4).** ADK agents are built with `Gemini(model=...)`; ADK can route other models through LiteLLM, but no work or eval exists. Not recommended for now.

**Embeddings.** OpenAI's own launch figures put text-embedding-3-large at 54.9 average on MIRACL; the BGE-M3 paper reports higher MIRACL nDCG@10 for bge-m3 dense retrieval (about 67 to 70 across 18 languages, corrected July 2024; see the [BGE-M3 model notes](https://deepinfra.com/BAAI/bge-m3-multi)). So quality is plausibly equal or better for Spanish and Arabic retrieval, but the money is negligible and the migration touches the schema, the whole corpus, and Stage 4's KB search.

### Hard blockers, summarized

1. **30-minute audio**: no documented per-request audio limit, and Cloudflare's own guidance is to chunk (1 MB in the tutorial). Workable with ffmpeg silence-splitting, but it is new code and a stitching step.
2. **Arabic ASR quality**: turbo is the only large Whisper offered, and it is the weakest Whisper on Arabic dialects in the published leaderboard.
3. **Prompt caching for 30k prompts**: available only on some models (GLM, DeepSeek, Qwen3.8, Kimi), instance-affine, and those cheap cached models are mostly "paid models" with 20 to 50 req/min caps.
4. **JSON schema enforcement**: best-effort, with an explicit failure error; needs validation and retry.
5. **Tool-calling reliability on our task**: unmeasured for every CF model.
6. **Rate limits at volume**: fine for ASR (720/min), detection (300/min) and embeddings (3,000/min) even at 10x; a real constraint for Stage 3 on paid models beyond about 2x.

## Live probe

Not run. Checks performed: no `CLOUDFLARE_*` or `CF_*` variables in the environment; `wrangler whoami` reports "Not logged in" (wrangler 4.95.0 installed); the Cloudflare MCP connectors in this session need re-authentication and in any case expose Workers bindings, not inference. No account was created and no keys were requested. The trial below includes the probe.

## Where Cloudflare would actually save money or add resilience (ranked)

1. **Stage 1 transcription on Whisper large-v3-turbo: about $327/day saved versus Phase 2 ($37 vs $365), or $43 to $121/day versus Phase 1.** By far the biggest number, and it grows linearly with volume ($3,270/day saved at 10x). It depends entirely on a quality test we have not run. Two safer shapes: Spanish stations only (Arabic stays on Gemini), or the hybrid where Whisper feeds detection for every recording and gemini-3.5-transcribe runs only on the ~39% that get flagged ($180/day, saving about $185/day, with Gemini-quality timestamps on everything that becomes a snippet).
2. **Stage 1 detection on Gemma 4 26B: $24 to $45/day saved versus 3.8 Flash@low, plus resilience.** Lowest risk because we have the recall numbers for this exact model. Best used either as the primary detector with 3.8 Flash as fallback, or as the fallback for Gemma 31B's free-tier 429s instead of paying for 3.8 Flash. A second provider for this stage also removes the single-vendor failure mode we keep hitting with Gemini quotas.
3. **Stage 3 on GLM-5.3-Flash or DeepSeek-V4.1-Flash: up to about $200/day on paper ($30 to $36 vs ~$234 cached Gemini), high risk.** Worth a 10-snippet spike only after items 1 and 2. Rate caps on these paid models limit it to about 1 to 2x current volume without an enterprise limit increase.
4. **AI Gateway in front of Gemini: no cost saving, some ops value.** Its cache is exact-match on the full request body (SHA-256 of provider, model, auth and body), so it will never hit on our requests, each of which carries a unique transcript or snippet; it does not do provider-side prefix caching, so Gemini context caching must still be done through the Gemini API. It could add logging, retries and provider fallback routing for free (5% fee only if using prepaid credits).
5. **R2 to Workers AI egress: no material change.** R2 egress is already free to anywhere ([R2 pricing](https://developers.cloudflare.com/r2/pricing/)), so pulling audio to Fly costs nothing today. A Worker reading R2 and calling `env.AI` would avoid streaming audio through Fly, a latency and simplicity gain, not a dollar one.
6. **Embeddings via bge-m3: under $0.40/day saved.** Not worth the migration for cost. Revisit only if retrieval quality on Spanish/Arabic becomes the reason, and fold it into VER-442's re-embed if that happens anyway.

## Two-day trial

Prerequisites (Rajiv): a Cloudflare account on Workers Paid ($5/month), an API token scoped to Workers AI only, and the account id exported as `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` in a scratch environment. Nothing touches production, Supabase or Fly. Expected spend under $10.

**Day 1: transcription and detection quality**
- Whisper: run `@cf/openai/whisper-large-v3-turbo` on the 18 eval mp3s (9 hours of audio, about $0.28 per pass). Split with ffmpeg on silence into roughly 2-minute chunks, pass the station language as `language`, try two settings (defaults; `vad_filter=true`, `condition_on_previous_text=false`, `hallucination_silence_threshold=2`). Score with the existing window-similarity harness against production transcripts and against gemini-3.5-transcribe, split by Spanish and Arabic. Count hallucinated text in music/ad segments by hand on 3 files. Record latency per chunk and any size errors (also try one 5-minute and one full 30-minute request to find the real limit).
- Detection: run `@cf/google/gemma-4-26b-a4b-it` through the OpenAI-compatible endpoint (`/ai/v1/chat/completions`) with the v4 prompt and `response_format: json_schema`, 3 runs on the same 18 files (about $0.03 per run). Compare human-hit /22, flags/file and precision with the Vertex runs to detect quantization drift. Log JSON-failure rate and retries.

**Day 2: end-to-end and limits**
- Feed Whisper transcripts (not production ones) into Gemma 26B and 3.8 Flash detection to see whether hit rates hold when the transcript source changes. This is the real test for the hybrid.
- Throughput: burst 300 detection requests and 500 ASR chunks to observe 429 behaviour, latency tails, and Batch API turnaround.
- Optional Stage 3 spike: point `eval/stage3_eval.py` at `@cf/zai-org/glm-5.3-flash` and `@cf/deepseek-ai/deepseek-v4.1-flash-1017` via OpenAI-style tools, 10 snippets each with `x-session-affinity` per snippet. Measure tool-call validity, whether citations come from tool results, cached-token share from `usage`, and cost. Budget about $5.

**Decision gates**
- Whisper adopted for Spanish if Spanish window similarity is within 3 points of 3.5-transcribe and hallucination is rare after VAD; for Arabic only if it reaches the 83 to 90 band (unlikely given published WER). Otherwise adopt the hybrid only if detection hit rate on Whisper transcripts is within one hit of the production-transcript baseline.
- Gemma 26B on CF adopted as detection fallback (or primary) if it reproduces 14+/22 with under 2% unrecoverable JSON failures.
- Stage 3 models proceed to a larger eval only if they match 3.8 Flash on verdicts for 8 of 10 snippets with no fabricated citations.

## Sources

- Workers AI pricing (updated 2026-10-20): https://developers.cloudflare.com/workers-ai/platform/pricing/
- Workers AI limits (updated 2026-09-17): https://developers.cloudflare.com/workers-ai/platform/limits/
- Model pages (accessed 2026-11-01): https://developers.cloudflare.com/workers-ai/models/gemma-4-26b-a4b-it/ , .../whisper-large-v3-turbo/ (and `schema-output.json`), .../whisper/ , .../nova-3/ , .../bge-m3/ , .../qwen3-embedding-0.6b/ , .../embeddinggemma-300m/ , .../glm-5.3-flash/ , .../deepseek-v4.1-flash-1017/ , .../deepseek-v4-flash-0731/ , .../qwen3.8-27b/ , .../qwen3-30b-a3b-fp8/ , .../gpt-oss-120b/ , .../llama-4-scout-17b-16e-instruct/ , .../llama-3.3-70b-instruct-fp8-fast/ , .../mistral-small-3.1-24b-instruct/ , .../nemotron-3-120b-a12b/ , .../glm-4.7-flash/ , .../gemma-sea-lion-v4-27b-it/
- Catalog index: https://developers.cloudflare.com/workers-ai/llms.txt
- JSON mode: https://developers.cloudflare.com/workers-ai/features/json-mode/
- Prompt caching: https://developers.cloudflare.com/workers-ai/features/prompt-caching/
- Batch API: https://developers.cloudflare.com/workers-ai/features/batch-api/
- Whisper chunking tutorial: https://developers.cloudflare.com/workers-ai/guides/tutorials/build-a-workers-ai-whisper-with-chunking/
- AI Gateway pricing: https://developers.cloudflare.com/ai-gateway/reference/pricing/ ; caching behaviour summarized from https://developers.cloudflare.com/ai-gateway/features/caching/ (via doc mirrors in search results)
- Workers pricing: https://developers.cloudflare.com/workers/platform/pricing/ ; R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Deepgram languages: https://developers.deepgram.com/docs/models-languages-overview
- Open Universal Arabic ASR Leaderboard: https://arxiv.org/html/2412.13788v1
- Careless Whisper: https://arxiv.org/abs/2402.08021v1
- Whisper turbo vs large-v3 by language (secondary): https://vexascribe.com/whisper-large-v3-vs-turbo
- Gemma 4: https://deepmind.google/models/gemma/gemma-4/ ; comparison pages https://llm-stats.com/models/compare/gemma-4-26b-a4b-it-vs-gemma-4-31b-it
- BGE-M3 MIRACL summary: https://deepinfra.com/BAAI/bge-m3-multi
- Internal: `eval/results_detection/*`, `eval/results_stage3/*`, `reports/prompt_tuning.md` in the session scratchpad; `src/processing_pipeline/stage_3/executors.py`, `stage_4/agents.py`, `stage_4/tools.py`, `stage_5/tasks.py`, `supabase/migrations/20260915000000_baseline_public_schema.sql` in the repo.
