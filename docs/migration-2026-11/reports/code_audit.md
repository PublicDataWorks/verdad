# Gemini feature dependency matrix (code audit, read-only)

Repo `/Users/j/GitHub/verdad`, branch `main` at c684029. All paths under `src/processing_pipeline/` unless noted. No call site reads a model name from an env var; every model is a hardcoded `GeminiModel` enum member (`constants.py:9-18`). Every Gemini call uses the API-key `genai.Client(api_key=GOOGLE_GEMINI_KEY)` (Gemini Developer API, not Vertex).

## 1. Call-site matrix

Today's models: stage 1 and the stage 3 fallback and structuring call use `gemini-2.5-flash`; stage 3 main uses `gemini-2.5-pro`; stage 4 researchers use 2.5 Flash, reviewer 2.5 Pro. Token sizes are my estimates (audio about 32 tokens/s, text about bytes/4).

### Stage 1 (sync, `stage_1/executors.py`, model chosen in `stage_1/tasks.py`)

| # | Call | file:line / class | Model and where set | Input | Features used |
|---|---|---|---|---|---|
| A | Initial transcription | `executors.py:21-61` `Stage1PreprocessTranscriptionExecutor.run` | `tasks.py:144` `GeminiModel.GEMINI_2_5_FLASH` (hardcoded) | **Files API**: `files.upload(file=...)` (l.32), poll `files.get` while PROCESSING, `files.delete` in `finally` (l.61). Whole 30 min mp3 (recorder: 1800 s, 64 kbps, `recording.py:140-141`), about 58k audio tokens + 2.9 KB prompt. Passed as `contents=[user_prompt, uploaded_file]` | `response_mime_type=application/json`; `response_schema` = tiny dict (1 string field, `initial_transcription_output_schema.json`, 204 B); `max_output_tokens=16384`; `thinking_budget=1024`; `safety_settings` (5 categories BLOCK_NONE, `processing_utils.py:26-48`). **No system_instruction** (manifest has `null`). No tools/temperature/cache/stream/aio |
| B | Initial detection | `executors.py:64-102` `Stage1PreprocessDetectionExecutor.run` | `tasks.py:174` Flash (hardcoded) | Text only. Prompt 22.6 KB (about 5.6k tokens) + transcript of a 30 min broadcast (roughly 5-8k tokens) + KB context | JSON mode; `response_schema` dict (960 B, 4 props, arrays of objects, depth 3 of nesting, no enums/refs); `system_instruction` (1.3 KB, `.get`, optional); `max_output_tokens=16384`; `thinking_budget=2048`; safety_settings |
| C | Timestamped transcription, per batch | `executors.py:210-251` `GeminiTimestampTranscriptionGenerator.transcribe_batch` | `tasks.py:320` and `flows.py:251` `transcriptor = GEMINI_2_5_FLASH`, passed as `model_name` | **Inline bytes**: 30 x 20 s mp3 segments per batch, `Part.from_bytes(..., "audio/mp3")` interleaved with `<Segment N>` text tags (l.222-228). About 19k audio tokens, about 1 MB, per request; 3 requests per 30 min file (90 segments), `time.sleep(2)` between | JSON mode; `response_schema` dict (776 B: `segments[{segment_number:int, transcript:str}]`); `system_instruction` (1.4 KB); `max_output_tokens=16384`; `thinking_budget = 128 if model == GEMINI_2_5_PRO else 0` (l.230, the only model-conditional code in the pipeline); safety_settings |
| D | Main detection | `executors.py:105-144` `Stage1Executor.run` | `tasks.py:334` and `flows.py:195, 272` Flash (hardcoded, separate from `transcriptor`) | Text only. Prompt 34 KB (about 8.5k tokens, includes the heuristics and the JSON schema pasted in the prompt text) + `[MM:SS]` transcript + KB context | JSON mode; `response_schema` dict (1.9 KB, `flagged_snippets[{start_time,end_time,transcription,explanation,disinformation_categories[],keywords_detected[]}]`, all `required`, no enums); `system_instruction` (565 B); `max_output_tokens=16384`; `thinking_budget=4096`; safety_settings |

Stage 1 shared facts:
- Parse: `result.parsed` is a plain dict (schema passed as dict, not Pydantic). Empty `parsed` -> `ValueError("No response from Gemini.")` or `"...too long and was cut off."` on `MAX_TOKENS` (A: l.52-57, B: l.95-100, D: l.137-142, C: l.245-249). Batch C also hard-fails on segment-count mismatch or out-of-range `segment_number` (l.180-198), so a model that merges or drops segments fails the whole file.
- Prompt format: B and D call `user_prompt.format(...)`, so the stored prompt text uses `{{ }}` escapes; any prompt edit must keep that.
- Retries: Prefect `@optional_task` only, all `retries=3` on the task wrappers (tasks.py:131, 160, 183, 205), no delay. C also has an inner `transcribe_batch` `retries=3, exponential_backoff(2)` (executors.py:211); the segment-count ValueError is raised in `run()`, outside `transcribe_batch`, so only the outer task retry covers it (re-transcribes the whole file). No `with_retries`, no fallback model. Any exception in `process_audio_file` -> audio file status `Error` with the message (tasks.py:375). Retries are inert when `ENABLE_PREFECT_DECORATOR=false`.
- Flow: `stage_1/flows.py:298-300` `_create_gemini_client` returns `None` without a key, tasks raise "Gemini client is not provided".
- Dead code: `transcribe_audio_file_with_open_ai_whisper_1` (tasks.py:87-127) is exported but never called in the flow.

### Stage 3 (async, `stage_3/executors.py`; models in `stage_3/constants.py:3-4`)

| # | Call | file:line | Model | Input | Features |
|---|---|---|---|---|---|
| E | Analysis with tool loop | `executors.py:211-309` `__analyze_with_web_search`, called from `run_async` l.166 | `MAIN_MODEL = GEMINI_2_5_PRO` (`stage_3/constants.py:3`), fallback `FALLBACK_MODEL = GEMINI_2_5_FLASH` (l.4), chosen in `stage_3/tasks.py:142-176` | Snippet clip (90 s before + snippet + 60 s after, `main.py:54`, so about 2.5-4 min, about 5-8k audio tokens) uploaded via **Files API** (l.157) and referenced by `Part.from_uri` (l.258). Text: `analysis_prompt.md` **131 KB (about 33k tokens)** + 5.5 KB system instruction + metadata. Up to 20 turns (`MAX_MODEL_TURNS`), each re-sending the full history including the audio URI | `system_instruction`; **function calling**: 2-3 `FunctionDeclaration.from_callable_with_api_option(...)` built from async Python callables (`searxng_web_search`, `web_url_read`, optional `jina_web_search`), `automatic_function_calling.disable=True`, manual loop with `Part.from_function_response`; `thinking_budget=4096, include_thoughts=True` (thought parts read at l.296-298; `thoughts_token_count` summed); `max_output_tokens=32768`; safety_settings; `aio`. **No response_schema/JSON mode** (tools and JSON mode are not combined); no temperature/cache/stream |
| F | Restructure fallback | `executors.py:397-443` `__structure_with_schema` | **Hardcoded `GEMINI_2_5_FLASH` (l.418)**, not `model_name` and not in constants | Text: the E answer (JSON text) + 1.2 KB inline system instruction | JSON mode; `response_schema` = prompt_version `output_schema` (`prompts/stage_3/output_schema.json`: **22 KB, 101 properties, nesting depth 12, 15 arrays, 4 enums, uses `nullable`**); `max_output_tokens=8192`; `thinking_budget=0`; safety_settings; aio |

Stage 3 parse chain: E returns `response.text`; `__validate_with_pydantic` slices from the first `{` to the last `}` and runs `Stage3Output.model_validate_json` (l.380-395, `stage_3/models.py:208`). On failure -> F, which needs `parsed["is_convertible"]` true or raises `ValueError`. Then `fill_publication_dates` + `apply_evidence_caps` (deterministic gate that relies on URLs the tool loop actually returned). The tool loop tolerates hallucinated tool names (l.353-358: maps by arg names `query`/`url`), which is the main hedge for a weaker tool-caller.

Retry semantics (`stage_3/tasks.py`, `gemini_retry.py`): `analyze_snippet` wraps `analyze_with_fallback` in `with_retries` (delays 30/120/300 s, 4 attempts; transient = HTTP 408/429/500/502/503/504, any `ValueError` including empty or truncated output, or an `ExceptionGroup` of those). Inside, **any** `errors.ServerError` or `ClientError` except 401/403 (including 400 INVALID_ARGUMENT, 404 model not found, 429) falls back to Flash once with the same prompt, tools and audio (tasks.py:154-171). Consequence for a swap: if Gemma rejects a feature with a 400, the code silently runs Flash instead, and `snippets.analyzed_by` is the only trace.

### Stage 4 (ADK, `stage_4/agents.py`, `executor.py`, `tasks.py`)

All four agents are built as `Gemini(model=<str>, retry_options=RETRY_OPTIONS)` instances (`agents.py:28-29`), which bypasses ADK's model registry regex. `RETRY_OPTIONS = HttpRetryOptions(attempts=6, initial_delay=10, max_delay=60)` (l.25). `GOOGLE_API_KEY` is set from `GOOGLE_GEMINI_KEY` (`stage_4/flows.py:23`). No `thinking_config`, no `safety_settings`, no temperature on any ADK agent (so server-default thinking on 2.5; safety defaults apply, unlike stages 1-3).

| # | Agent | file:line | Model and where set | Input | Features |
|---|---|---|---|---|---|
| G | kb_researcher | `agents.py:73-80` | `GEMINI_2_5_FLASH` hardcoded at l.76 | Text. Instruction 5.9 KB; ADK injects session state (`{analysis_json}`, `{transcription}` etc.) into the instruction | system instruction (ADK `instruction`); function tool `search_knowledge_base` (Python callable via `FunctionTool`, which embeds the query with OpenAI first, `tools.py:37-44, 72`); ADK automatic tool loop; output as free text into `output_key="kb_research"` |
| H | web_researcher | `agents.py:83-91` | Flash hardcoded at l.86 | Text. Instruction 11 KB | system instruction; **MCP toolset** (`GeminiSafeMcpToolset`, stdio `npx mcp-searxng@2.2.0`, tools `searxng_web_search`, `web_url_read`, `gemini_mcp_toolset.py`); **forced function calling**: `before_model_callback=force_first_search` sets `tool_config.function_calling_config.mode=ANY, allowed_function_names=["searxng_web_search"]` on the first turn (l.32-40, VER-406); schema sanitising for Gemini enum rules (int enums to str, `time_range` hidden); text output `web_research` containing a machine-readable evidence block parsed by `stage_4/evidence.py` |
| I | analysis_reviewer | `agents.py:94-104` | `reviewer_model` argument; **`stage_4/tasks.py:175` `reviewer_model = GEMINI_2_5_PRO`** (hardcoded in the task), passed through `executor.py:84` | Text. Instruction **50 KB (about 12k tokens)** + state (analysis JSON, kb_research, web_research, transcription) | system instruction; `output_schema=ReviewAnalysisOutput` (Pydantic, `stage_4/models.py:14`, nested models from `stage_3/models.py` with `Literal` enums and `ge/le` bounds, so `$defs/$ref` plus `minimum/maximum` in the schema; the manifest's `stage_4/output_schema.json` is 10.9 KB, 56 props, depth 10, and is **not** what the code uses). ADK sets `response_schema=<Pydantic class>` and `response_mime_type=application/json` (no tools on this agent, so no workaround path); `max_output_tokens=16384`; no thinking config |
| J | kb_updater | `agents.py:107-117` | `KB_WRITER_MODEL = GEMINI_2_5_FLASH` (`stage_4/constants.py:14`) | Text, 12 KB instruction | function tools `upsert_knowledge_entry`, `deactivate_knowledge_entry`. **Disabled** (`KB_UPDATER_ENABLED = False`, constants.py:28), so not in the pipeline today |

Stage 4 parse and failure: the reviewer result is `session.state["revised_analysis"]`; empty -> `ValueError` (executor.py:152-153), else `json.loads` if a string (l.154). Invalid JSON from the reviewer surfaces as a pydantic `ValidationError` or `JSONDecodeError` inside ADK, wrapped in an `ExceptionGroup`. Both are `ValueError` subclasses (pydantic v2; from library knowledge, not run here), so `with_retries` (30/120/300 s) treats them as transient and re-runs the entire 4-agent pipeline. Final failure -> snippet status `Error` with `[Stage 4] ...` (tasks.py:233-234). Tool errors are returned to the model by `ToolErrorHandlerPlugin` (executor.py:19-34). No fallback model. Stage 4 sessions are in-memory (`InMemorySessionService`); no context cache.

### Embeddings (not Gemini; no swap needed)

| Call | file:line | Model | Persisted as |
|---|---|---|---|
| Stage 5 snippet embedding | `stage_5/tasks.py:56`, `stage_5/executors.py:10` | OpenAI `text-embedding-3-large`, L2-normalised | `snippet_embeddings.model_name` (tasks.py:76) |
| KB retrieval, Stage 1 | `stage_1/kb_context.py:29` (batch of 2000-char chunks) | same | none |
| KB retrieval and dedup, Stage 4 | `stage_4/tools.py:43, 338, 348` | same | `kb_entry_embeddings.model_name` |

Moving off OpenAI embeddings would mean re-embedding every stored vector; out of scope for a Gemma/Gemini choice.

### Features by call (what a candidate model must support)

| Feature | A init-transcr | B init-detect | C ts-batch | D main-detect | E stage 3 | F restructure | G/H/I/J stage 4 |
|---|---|---|---|---|---|---|---|
| system_instruction | no | yes (optional) | yes | yes | yes | yes | yes (all) |
| JSON mode + response_schema | yes (trivial) | yes (small) | yes (small) | yes (small) | no | yes (22 KB, deep) | I only (Pydantic) |
| thinking_config | budget 1024 | 2048 | 0 (128 on Pro) | 4096 | 4096 + include_thoughts | 0 | none set |
| safety_settings | yes | yes | yes | yes | yes | yes | no |
| function calling | no | no | no | no | yes (manual loop) | no | G, H (forced ANY), J |
| Files API | yes | no | no (inline bytes) | no | yes | no | no |
| audio input | 30 min via file | no | 30 x 20 s inline | no | 3-4 min via file | no | no |
| max_output_tokens | 16384 | 16384 | 16384 | 16384 | 32768 | 8192 | I: 16384 |
| async (`aio`) | no | no | no | no | yes | yes | ADK async |
| cached content, temperature, streaming | none anywhere |||||||

Gemma-sensitive dependencies, ranked: (1) E needs native function calling plus thought parts plus audio, and a 33k-token prompt re-sent each turn; (2) H needs forced `mode=ANY`; (3) F/I need large-schema structured output; (4) C needs 20 untrimmed inline audio clips per request and exact count and index fidelity; (5) A needs Files API plus 30 min audio. B and D are text-only with small schemas, the least feature-dependent.

### Where the model name is persisted

| Column | Written by | Value today | Gap |
|---|---|---|---|
| `stage_1_llm_responses.transcriptor` (text; comment "model used to create timestamped transcript") | `supabase_utils.py:199, 408`, from `tasks.py:320` / `flows.py:251` | `"gemini-2.5-flash"` (StrEnum; `None` when no initial snippets were flagged, tasks.py:311). Test fixtures also use legacy `"gemini-1206"` | Records only the timestamping model. **Initial transcription, initial detection and main detection models are not stored**; only `detection_prompt_version_id` / `transcription_prompt_version_id` (not for the two initial prompts). A detection-model swap is invisible in data |
| `snippets.analyzed_by` | `stage_3/tasks.py:212` | `MAIN_MODEL` or `FALLBACK_MODEL` as actually used | Good; shows silent fallbacks |
| `snippets.reviewed_by` | `stage_4/tasks.py:223` `reviewer_model.value` | `"gemini-2.5-pro"` | Only the reviewer; researcher models not stored |
| `kb_entries.created_by_model` | `stage_4/tools.py:296, 321` | `KB_WRITER_MODEL.value` | `kb_context.py:65 is_pipeline_authored` is `startswith("gemini")`, so a Gemma-authored KB entry would be treated as **human-authored** (skips the date requirement) if kb_updater were re-enabled |
| `snippet_embeddings.model_name`, `kb_entry_embeddings.model_name` | stage 5, stage 4 tools | `text-embedding-3-large` | n/a |

`supabase/migrations/20260915000000_baseline_public_schema.sql:2763-2768` groups a stats report by `transcriptor`, so a new value shows up as a new bucket there.

## 2. Single switch points

Minimum edits per stage (all currently hardcoded; none read env):

| Stage | Locations |
|---|---|
| 1 initial transcription / initial detection | `stage_1/tasks.py:144`, `:174` |
| 1 timestamped transcription | `stage_1/tasks.py:320` (`transcriptor`) and `stage_1/flows.py:251` (regenerate flow); `executors.py:230` has the Pro-only thinking branch |
| 1 main detection | `stage_1/tasks.py:334`, `stage_1/flows.py:195` (redo_main_detection), `:272` (regenerate flow) |
| 3 | `stage_3/constants.py:3-4` (main and fallback); plus `stage_3/executors.py:418` (hardcoded Flash for F) |
| 4 researchers | `stage_4/agents.py:76, 86` |
| 4 reviewer | `stage_4/tasks.py:175` (note: not in `stage_4/constants.py`) |
| 4 kb_updater | `stage_4/constants.py:14` |
| Enum | add members to `constants.py:9-18` `GeminiModel` (every call site types `model_name: GeminiModel`, and `.value` is used at `stage_4/tasks.py:223`, `agents.py:29`, `tools.py:296`) |

Env-var configurability without touching flow topology: yes for all of them. The names are read inside task or executor bodies, not at import or flow wiring, so replacing the literals with `os.getenv("STAGE1_TRANSCRIBE_MODEL", default)` (or a small `models.py` mapping) changes no flow signatures, deployments or `FLY_PROCESS_GROUP` dispatch. The only structural wrinkle is `GeminiModel` being a closed StrEnum with `.value` calls; use `str` values or extend the enum. `src/scripts/evaluate_prompt.py:806` already exposes `--model` for Stage 3 A/B runs (defaults to `MAIN_MODEL`; it passes only `model_name`, so F stays Flash; its price table `evaluate_prompt.py:81-84` only has the two 2.5 models, so cost shows "n/a"). `scripts/run_stage.py` has no model flag; no other script chooses a model.

## 3. Timestamp pipeline

1. **Segmenting** (`stage_1/executors.py:268-287`): `AudioSegment.from_mp3(audio_file)`; cut into `segment_length_ms = 20 * 1000` slices (`tasks.py:199-200` passes `segment_length=20, batch_size=30`), exported as `<file>_segment_N.mp3`. The last segment can be shorter than 20 s.
2. **Batching** (l.167-201): 30 segments per request; model returns `segments[{segment_number, transcript}]` with batch-relative numbers 1..30; code validates count and range, then rebases `absolute = batch_start + segment_num` (l.197). The model never sees real time; time is derived purely from segment index.
3. **Formatting** (`format_final_transcription`, l.253-266): `total_seconds = (segment_num - 1) * 20`, line `f"[{minutes:02}:{seconds:02}] {transcript}\n"`. Always `MM:SS` (minutes unbounded, never HH). Possible values are 00:00, 00:20, 00:40, 01:00... The tag is the segment's **start**.
4. **Storage**: `{"timestamped_transcription": "<text>"}` dict stored in `stage_1_llm_responses.timestamped_transcription` with `transcriptor`.
5. **Main detection** (`detection_user_prompt.md` l.18-27, 848-850; schema `detection_output_schema.json`): the model must output `start_time` / `end_time` strings `MM:SS` "accurate and correspond to those provided in the timestamped transcription", `start <= end`, within range. So both values are nominally copies of tag values (multiples of 20 s); `end_time` is the **start tag of the last flagged segment**, which means up to 19 s of the final flagged segment lies after `end_time`. The prompt's own examples (`"05:30"`, `"07:15"`, `"08:00"`, l.822-831) are not multiples of 20 and contradict the granularity. The schema has no `pattern` or enum, so nothing forces conformance; the model could emit finer values.
6. **UUIDs** assigned in `tasks.py` `disinformation_detection_with_gemini` (`snippet["uuid"] = uuid4()`).
7. **Stage 2** (`stage_2/tasks.py`): `ensure_correct_timestamps` (l.152-168) converts with `convert_formatted_time_str_to_seconds` (l.43-56; accepts `HH:MM:SS`, `MM:SS` or `SS`, `float` then `int(round())`) and raises if `start > end` or `end > duration`; any failing snippet fails the whole stage-1 response (`Error`). `extract_snippet_clip` (l.60-123) cuts `[start - context_before, end + context_after]` clamped to `[0, duration]`; context seconds come from `main.py:54` (`context_before_seconds=90, context_after_seconds=60`) and `scripts/run_stage.py:85-86` defaults. It stores the snippet's offsets **relative to the clip**: `snippet_start = start - new_start`, formatted `MM:SS` (l.95-108). `SupabaseClient.ensure_time_format` (`supabase_utils.py:246-258`) prepends `00:` so the `time without time zone` columns (`snippets.start_time/end_time/duration`) hold `00:MM:SS`.
8. **Stage 3** (`stage_3/tasks.py:130-132`): `start_time/end_time/duration = value.split(":", 1)[1]` strips the `00:` and passes `MM:SS` into the analysis metadata (`analysis_prompt.md` l.13-15 says these are MM:SS within the clip).

Assumptions about 20 s granularity or the `[MM:SS]` shape: `executors.py:156-157` defaults and `tasks.py:199-200`; `format_final_transcription`; the detection prompt text; the 90/60 s padding in stage 2 absorbing the up-to-20 s end truncation (tail padding is 3x the granularity, the lead is 4.5x); stage 3 `.split(":", 1)[1]` assumes a `00:` prefix; `tests/processing_pipeline/test_stage_1.py` asserts `"[00:00] seg 1\n[00:20] seg 2\n[00:40] seg 1\n"` (l.344) and `"[00:00] regenerated"`.

Implications for a swap: a dedicated transcription model that returns native word or segment timestamps would not need the 20 s batching, but then `format_final_transcription` and the segment-count validation need a replacement that still emits `[MM:SS]` lines, and stage 2 would accept finer values without change (it rounds to whole seconds). The unused Whisper path (`tasks.py:87-127`) already formats `[MM:SS]` from segment `start`, so that shape is the contract.

`stage_1_llm_responses.transcriptor` values in code: `GeminiModel.GEMINI_2_5_FLASH` ("gemini-2.5-flash") at `tasks.py:320` and `flows.py:251`; `None` at `tasks.py:311` (no initial flags). Tests also use `"gemini-1206"` (`tests/test_supabase_utils.py:206, 348`) and `"gemini-2.5-flash"` (`test_stage_1.py:546`). Legacy comments in the baseline migration mention OpenAI/Gemini 1.5 for older rows.

## 4. Test surface

Mocking style: no real network. Stage 1 executor tests use `client = Mock()` with `client.models.generate_content.return_value = result` where `result.parsed` and `result.candidates=[Mock(finish_reason=...)]` are set (`test_stage_1.py:~225-235`). Flow tests patch names where bound (`processing_pipeline.stage_1.flows.genai`, `.SupabaseClient`, `.OpenAI`). Stage 3 uses `mock_run` on `Stage3Executor.run_async` plus async mocks of `client.aio.models.generate_content`. Stage 4 patches `Stage4Executor.run_async` and, for `build_review_pipeline`, inspects real ADK objects. `tests/conftest.py` sets `ENABLE_PREFECT_DECORATOR=false` and fake keys.

Files that pin model names or model-specific config and would need edits:

| File | What is pinned |
|---|---|
| `tests/processing_pipeline/test_stage_1.py` | `GeminiModel.GEMINI_2_5_FLASH` as model arg and asserted call kwargs (l.176-248, 320-337, 479-493, 706-709); `thinking_budget == 4096` (l.252); `test_transcribe_batch_config` parametrised `(FLASH, 0), (PRO, 128)` (l.381); safety category set (l.~275-285); `max_output_tokens == 16384`; `transcriptor="gemini-2.5-flash"` (l.546, 556) |
| `tests/processing_pipeline/test_stage_3.py` | `MAIN_MODEL`/`FALLBACK_MODEL` identity: `analyzed_by == GEMINI_2_5_PRO/FLASH` (l.177-198, 241-248, 295-297, 326-329, 391-419) |
| `tests/processing_pipeline/test_stage_3_tool_loop.py` | `model_name=GEMINI_2_5_PRO` (l.51); asserts on `GenerateContentConfig` tool and AFC settings |
| `tests/processing_pipeline/test_stage_4.py` | `reviewed_by="gemini-2.5-pro"` (l.130-163, 209-221); **`test_every_agent_retries_429_inside_the_run` pins the exact model string per agent and `isinstance(m, Gemini)`** (l.665-681), the one test that would fail on any ADK model swap, and would fail for a non-`Gemini` class such as ADK's `Gemma` |
| `tests/test_evaluate_prompt.py` | `"gemini-2.5-pro"` price-table key (l.171-481) |
| `tests/test_supabase_utils.py` | `"gemini-1206"`, `analyzed_by`, `reviewed_by` literals (l.206-353, 697-717); pass-through only, would not break |
| `tests/processing_pipeline/test_kb_tools.py`, `test_kb_context.py` | `created_by_model` values and the `startswith("gemini")` rule (`test_kb_context.py:53-56`); would need a case if `is_pipeline_authored` changes |
| `tests/processing_pipeline/test_gemini_retry.py`, `test_gemini_mcp_toolset.py` | name-independent (retry classification, schema sanitising) |

If model names become env-driven, most pins can instead assert against the constant, so the edit is mechanical.

## 5. Dependencies

| Package | `requirements.txt` | Notes |
|---|---|---|
| google-genai | `==1.62.0` | I downloaded the 1.62.0 wheel and read it: `ThinkingConfig` has `include_thoughts`, `thinking_budget` **and `thinking_level`**; `ThinkingLevel` enum = `LOW, MEDIUM, HIGH, MINIMAL` (types.py:308-320, 4628-4644). No client-side model-name validation was found (model is a string; Gemma/3.x names pass through). The pinned SDK can send `thinking_level`; the API may reject `thinking_budget` on Gemini 3.x or combine it with `thinking_level` (server-side behaviour I did not verify). Note the machine's default `python3` has google-genai **1.24.0**, which has no `thinking_level`; use the project venv |
| google-adk | `==1.24.1` | Wheel inspected. `Gemini.supported_models` = `gemini-.*` etc.; a separate `Gemma` class (`gemma_llm.py`) matches only `gemma-3.*`, is **Gemini API only (no Vertex)**, and rewrites system instructions into a first user message and function calls into prompt text ("Gemma does NOT support system instructions... no special API support for tools"). This repo constructs `Gemini(model=str)` directly, so a `gemma-4-*` string is not blocked by the registry but would be sent with native system_instruction/tools, which ADK does not adapt for Gemma. Gemma 4's actual API capabilities are not documented in this repo and I did not verify them |
| pydub | `==0.25.1` | `AudioSegment.from_mp3` needs ffmpeg |
| openai | `==1.57.1` | embeddings only (Whisper path unused); machine default is 1.12.0 |
| others | `pydantic==2.12.5`, `tiktoken==0.8.0`, `prefect==3.4.24`, `supabase==2.22.0` | `pyproject.toml` carries only pytest and coverage config and `requires-python >=3.11`; no dependency list |

Did not run: tests or pipeline code (the local `.venv` is not usable per memory; system python lacks prefect/adk), and no model call was made. Token estimates are from file sizes and a 32 tokens/s audio rate, not measured.

## Also found

- `stage_4/tasks.py:175` hardcodes the reviewer model while `stage_3` uses a constants file; stage 4 has no single place.
- Stage 4 agents set no `safety_settings`, unlike stages 1-3, so radio content could hit default blocks on any new model.
- The Stage 3 `analysis_prompt.md` (131 KB) is re-sent on every tool turn with no caching, which dominates cost and context needs for any candidate.
