-- VER-454 item 2: score snippets already in New, which the 20261104100000 trigger never saw. Run in its own request
-- after 20261104100000 commits, so its ADD COLUMN lock is not held meanwhile; re-run after loading a station-hour
-- ranking. Fires snippets_handle_updated_at per row; harmless, as sweep_stuck_snippets keys on Processing/Reviewing.

UPDATE public.snippets
SET priority = public.snippet_priority(audio_file, recorded_at)
WHERE status = 'New';
