#!/usr/bin/env python3
"""Fill data/<audio_file_id>.json with the full stage_1 + snippet payload (read-only SELECTs).
Usage: SUPABASE_DB_URL=postgres://... python3 build_data.py
Primary stage_1 row = the Processed row with the most linked snippets (ties: earliest). Other rows go in stage_1_other_rows.
Snippets include every snippet of the audio file (all stage_1 rows), each tagged with stage_1_llm_response."""
import json, os, subprocess, sys
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
URL = os.environ["SUPABASE_DB_URL"]
Q = """
with a as (select * from audio_files where id = '{id}'),
r as (select r.*, (select count(*) from snippets s where s.stage_1_llm_response=r.id) n_snip from stage_1_llm_responses r where r.audio_file='{id}'),
prim as (select * from r order by (status='Processed') desc, n_snip desc, created_at limit 1)
select json_build_object(
 'audio_file',(select json_build_object('id',id,'radio_station_code',radio_station_code,'radio_station_name',radio_station_name,'location_state',location_state,'location_city',location_city,'recorded_at',recorded_at,'file_path',file_path,'file_size',file_size) from a),
 'stage_1',(select json_build_object('id',id,'transcriptor',transcriptor,'status',status,'created_at',created_at,
     'initial_transcription',initial_transcription,'timestamped_transcription',timestamped_transcription->>'timestamped_transcription',
     'flagged_snippets',detection_result->'flagged_snippets','initial_detection_result',initial_detection_result) from prim),
 'stage_1_other_rows',(select coalesce(json_agg(json_build_object('id',id,'status',status,'created_at',created_at,'n_snippets',n_snip)),'[]'::json) from r where id <> (select id from prim)),
 'snippets',(select coalesce(json_agg(json_build_object('id',s.id,'stage_1_llm_response',s.stage_1_llm_response,'start_time',s.start_time,'end_time',s.end_time,'duration',s.duration,'file_path',s.file_path,
     'transcription',s.transcription,'title',s.title,'disinformation_categories',s.disinformation_categories,'confidence_scores',s.confidence_scores,'language',s.language,'status',s.status,'reviewed_at',s.reviewed_at,'political_leaning',s.political_leaning,
     'human_labels',coalesce((select json_agg(l.text order by l.text) from snippet_labels sl join labels l on l.id=sl.label where sl.snippet=s.id and sl.applied_by is not null),'[]'::json)) order by s.start_time, s.id),'[]'::json) from snippets s where s.audio_file='{id}')
)::text
"""
for m in json.load(open(os.path.join(D, "manifest.json"))):
    aid = m["audio_file_id"]
    out = subprocess.run(["psql", URL, "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", Q.format(id=aid)], capture_output=True, text=True)
    if out.returncode: sys.exit(f"{aid}: {out.stderr}")
    full = json.loads(out.stdout)
    full.update(local_audio=m["local_audio"], n_snippets=len(full["snippets"]))
    json.dump(full, open(os.path.join(D, f"{aid}.json"), "w"), ensure_ascii=False, indent=1)
    print(aid, len(full["snippets"]), "snippets", len(full["stage_1"]["timestamped_transcription"] or ""), "ts chars")
