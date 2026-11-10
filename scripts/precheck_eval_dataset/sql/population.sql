-- VER-475 pre-check eval: the population, as one jsonb_agg value (read-only).
-- Population: non-copy snippets scored by Stage 3 with gemini-3.5-flash or gemini-3.8-flash since 2026-11-06.
-- Change the model list and the date here and in details.sql together.
-- Stage 3 score: when Stage 4 has backed the row up (previous_analysis not null), the pre-review values live in
-- previous_analysis; otherwise the live columns are still Stage 3's (Stage 3's update_snippet nulls previous_analysis).
-- No analyzed_at column exists: updated_at (or previous_analysis->>'updated_at' for reviewed rows) is the proxy.
select jsonb_agg(jsonb_build_object(
  'id', s.id,
  'analyzed_by', s.analyzed_by,
  'prev_analyzed_by', s.previous_analysis->>'analyzed_by',
  'status', s.status,
  'final_overall', s.confidence_scores->>'overall',
  'prev_overall', s.previous_analysis->'confidence_scores'->>'overall',
  'has_prev', s.previous_analysis is not null,
  'reviewed_at', s.reviewed_at,
  'reviewed_by', s.reviewed_by,
  'stage3_prompt_version_id', s.stage_3_prompt_version_id,
  'prev_prompt_version_id', s.previous_analysis->>'stage_3_prompt_version_id',
  'updated_at', s.updated_at,
  'prev_updated_at', s.previous_analysis->>'updated_at',
  'recorded_at', s.recorded_at,
  'lang_final', s.language->>'primary_language',
  'lang_prev', s.previous_analysis->'language'->>'primary_language',
  'station_code', s.radio_station_code,
  'location_state', s.location_state,
  'priority', s.priority,
  's1_id', s.stage_1_llm_response,
  'start_time', s.start_time,
  'end_time', s.end_time,
  'duration', s.duration
) order by s.id)
from snippets s
where s.analyzed_by in ('gemini-3.5-flash', 'gemini-3.8-flash')
  and s.repeat_of is null
  and s.updated_at >= '2026-11-06'
  and coalesce(s.previous_analysis->'confidence_scores'->>'overall', s.confidence_scores->>'overall') is not null;
