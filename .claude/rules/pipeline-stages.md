---
paths:
  - "src/processing_pipeline/**"
---

# Processing pipeline (stages 1-5)

## Shape of a stage package

`flows.py` holds the Prefect flow (decorated with `optional_flow` from `src/utils.py`), `tasks.py` the steps,
`executors.py` the LLM call. Stage 2 has no executor (pydub clipping only); stage 4 uses `executor.py` plus
`agents.py`. `models.py`, `constants.py` and helpers such as `stage_3/web_tools.py` are stage-local.

Flows build their own clients (`boto3`, `genai.Client`, `OpenAI`, `SupabaseClient`) from `os.getenv` inside the
function body, then pass them down into tasks. Nothing is constructed at import time, so a missing env var
surfaces as an error once the flow runs.

## Fetching work and writing status

`src/processing_pipeline/supabase_utils.py` is the only DB layer. Stages claim work through reserve-RPCs, never
plain selects: `get_a_new_audio_file_and_reserve_it`, `get_a_new_stage_1_llm_response_and_reserve_it`,
`get_a_new_snippet_and_reserve_it`, `get_a_ready_for_review_snippet_and_reserve_it`,
`get_a_snippet_that_has_no_embedding`. The SQL behind them lives in `supabase/database/sql/`.

Status is written with `set_audio_file_status`, `set_stage_1_llm_response_status` and `set_snippet_status`
(each takes an optional `error_message`, and only writes the column when one is passed). Use the
`ProcessingStatus` StrEnum in `processing_pipeline/constants.py`, not literals: `New`, `Processing`,
`Processed`, `Error`, `Ready for review`, `Reviewing`. `submit_snippet_review` and `reset_snippet` set
`Processed` / `New` directly.

## Loop semantics

Stages 2-5 take a `repeat` flag: the flow loops, sleeps 2s after doing work and 60s when idle, and breaks
immediately when `repeat=False`. Stage 1 has no `repeat`; it takes `limit` (1000/10000 in production) and
breaks once `processed_audio_files >= limit` or when a specific `audio_file_id` was passed. Always pass
`repeat=False` or a specific id when invoking a flow yourself.

## Prompts, thresholds, async

- Prompts come from the `prompt_versions` table via `supabase_client.get_active_prompt(PromptStage, sub_stage)`,
  loaded once at flow start and threaded through tasks as a `prompt_version` dict
  (`system_instruction` / `user_prompt` / `output_schema`). Editing files in `prompts/` changes nothing.
- `CONFIDENCE_THRESHOLD = 95` (`constants.py`): stage 3 sends a snippet to stage 4 only when
  `confidence_scores.overall >= CONFIDENCE_THRESHOLD` and `skip_review` is false (`stage_3/tasks.py`).
- Executors are classes with a `run`/`run_async` `@classmethod` taking the client first
  (`gemini_client: genai.Client`, or `openai_client: OpenAI` in stage 5). Stage 3 and stage 4 flows are
  `async def` and call `gemini_client.aio.*`; stage 1, 2 and 5 are synchronous.
- Stage 3 runs its own tool-calling loop (`WEB_TOOLS`, `MAX_MODEL_TURNS` in `stage_3/executors.py`) with the SDK's
  automatic function calling disabled, so a hallucinated tool name is answered with a function-response error
  instead of failing the analysis; `run_async` returns the token `usage` summed over every model turn.
- Stage 4 is a Google ADK pipeline (`LlmAgent`/`ParallelAgent`/`SequentialAgent` in `agents.py`) with MCP
  tools; it sets `GOOGLE_API_KEY` from `GOOGLE_GEMINI_KEY` at flow start.

## Testing this code

- `ENABLE_PREFECT_DECORATOR` is read at import time by `optional_flow`/`optional_task`. Set it before
  importing anything from `src/`; `tests/conftest.py` and `scripts/run_stage.py` already do.
- Patch names where they are bound, i.e. module-level in the stage you are exercising:
  `processing_pipeline.stage_1.flows.SupabaseClient`, `...flows.genai`, `...flows.OpenAI`,
  `processing_pipeline.stage_3.tasks.postprocess_snippet`,
  `processing_pipeline.stage_4.tasks.Stage4Executor.run_async`. Patching `google.genai` or `supabase` itself
  leaves the already-imported name untouched and the test hits the network.
- Patch the sleep too (`time.sleep`, or `...flows.asyncio.sleep` in stages 3 and 4, and
  `processing_pipeline.gemini_retry.asyncio.sleep` when an executor mock raises) or a test takes minutes.
  No test may call real Gemini, OpenAI, R2 or Supabase.

## Before changing flow topology

Use plan mode for changes to any `flows.py` control flow, deployment names or `main.py` dispatch: each
`FLY_PROCESS_GROUP` in `fly.processing_worker.toml` serves one deployment by name in production.
