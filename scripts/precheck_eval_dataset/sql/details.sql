-- VER-475 pre-check eval: pre-Stage-3 details for one page of the population, as one jsonb_agg value (read-only).
-- Page = the leading hex digit(s) of snippets.id, given as a comma list in the psql variable :'prefixes'
-- (psql -v prefixes=0 or -v prefixes=1,2,3). `build_dataset.py render-sql` substitutes it for MCP use.
-- Keep the population filter identical to population.sql.
-- Clip window (what Stage 2 cut and Stage 3 heard): Stage 2 stores start_time = flag_start - clip_start, so
-- clip_start = flag_start - snippets.start_time and clip_end = clip_start + snippets.duration (seconds into the
-- recording). The excerpt is every Stage 1 word (timestamped_transcription->'words') overlapping that window.
with ids(id) as (
  select s.id from snippets s
  where s.analyzed_by in ('gemini-3.5-flash', 'gemini-3.8-flash') and s.repeat_of is null
    and s.updated_at >= '2026-11-06'
    and coalesce(s.previous_analysis->'confidence_scores'->>'overall', s.confidence_scores->>'overall') is not null
    and left(s.id::text, 1) = any(string_to_array(:'prefixes', ','))
),
s as (
  select s.id, s.stage_1_llm_response, s.audio_file, s.start_time, s.end_time, s.duration,
         extract(epoch from s.start_time)::numeric as st, extract(epoch from s.duration)::numeric as dur
  from snippets s join ids using (id)
),
f as (
  select s.*, r.transcriptor, r.status as s1_status, r.created_at as s1_created_at,
         r.detection_prompt_version_id, r.transcription_prompt_version_id,
         jsonb_array_length(r.detection_result->'flagged_snippets') as n_flagged,
         (select fs from jsonb_array_elements(r.detection_result->'flagged_snippets') with ordinality x(fs, i)
           where fs->>'uuid' = s.id::text limit 1) as flagged,
         (select i from jsonb_array_elements(r.detection_result->'flagged_snippets') with ordinality x(fs, i)
           where fs->>'uuid' = s.id::text limit 1) as flagged_index,
         r.timestamped_transcription->'words' as words,
         jsonb_array_length(r.timestamped_transcription->'words') as n_words_total
  from s join stage_1_llm_responses r on r.id = s.stage_1_llm_response
),
t as (
  select f.*,
    (select coalesce(sum(p::numeric * power(60, n - o)), 0)
       from unnest(string_to_array(f.flagged->>'start_time', ':')) with ordinality u(p, o),
            lateral (select array_length(string_to_array(f.flagged->>'start_time', ':'), 1) n) c) as fs_s,
    (select coalesce(sum(p::numeric * power(60, n - o)), 0)
       from unnest(string_to_array(f.flagged->>'end_time', ':')) with ordinality u(p, o),
            lateral (select array_length(string_to_array(f.flagged->>'end_time', ':'), 1) n) c) as fe_s
  from f
)
select jsonb_agg(jsonb_build_object(
  'id', t.id,
  'transcriptor', t.transcriptor, 's1_status', t.s1_status, 's1_created_at', t.s1_created_at,
  'detection_prompt_version_id', t.detection_prompt_version_id,
  'transcription_prompt_version_id', t.transcription_prompt_version_id,
  'n_flagged', t.n_flagged, 'flagged_index', t.flagged_index, 'flagged', t.flagged,
  'snip_start_time', t.start_time, 'snip_end_time', t.end_time, 'snip_duration', t.duration,
  'flag_start_s', t.fs_s, 'flag_end_s', t.fe_s,
  'clip_start_s', t.fs_s - t.st, 'clip_end_s', t.fs_s - t.st + t.dur,
  'n_words_total', t.n_words_total,
  'last_word_end', (t.words->-1->>'end')::numeric,
  'clip_excerpt', (select string_agg(w->>'text', ' ' order by o) from jsonb_array_elements(t.words) with ordinality x(w, o)
                    where (w->>'start')::numeric < t.fs_s - t.st + t.dur and (w->>'end')::numeric > t.fs_s - t.st),
  'core_excerpt', (select string_agg(w->>'text', ' ' order by o) from jsonb_array_elements(t.words) with ordinality x(w, o)
                    where (w->>'start')::numeric < t.fe_s and (w->>'end')::numeric > t.fs_s),
  'station_name', a.radio_station_name, 'station_code', a.radio_station_code,
  'location_state', a.location_state, 'location_city', a.location_city,
  'audio_recorded_at', a.recorded_at, 'audio_file_id', a.id
) order by t.id)
from t left join audio_files a on a.id = t.audio_file;
