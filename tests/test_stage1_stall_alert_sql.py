"""VER-487: the Stage 1 stall check alerts once per stall, only while recordings wait, and only from pg_cron."""

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
MIGRATION = MIGRATIONS_DIR / "20261117100000_stage1_stall_alert.sql"
PREFIX_MIGRATION = MIGRATIONS_DIR / "20261117120000_stage1_stall_alert_prefix.sql"
SIGNATURE = "public.check_stage1_stall(integer, integer, boolean)"


def sql():
    return MIGRATION.read_text()


def function_body(path=PREFIX_MIGRATION):
    text = path.read_text()
    start = text.index("CREATE OR REPLACE FUNCTION public.check_stage1_stall(")
    return text[start : text.index("$function$;", start)]


def test_alert_starts_with_a_cross_and_nothing_else_changed():
    assert function_body().replace("format('❌ Stage 1", "format('Stage 1") == function_body(MIGRATION)
    assert "v_text := format('❌ Stage 1 monitor: no recording finished" in function_body()


def test_window_is_the_last_24_hours_of_recordings():
    assert "recorded_at >= v_now - interval '24 hours'" in function_body()


def test_stall_needs_waiting_recordings_and_no_recent_finish():
    body = function_body()
    assert "status IN ('New', 'Processing') AND a.created_at < v_now - v_stall" in body
    assert "max(a.updated_at) FILTER (WHERE a.status = 'Processed')" in body
    assert "v_waiting >= p_min_waiting AND (v_last_done IS NULL OR v_last_done < v_now - v_stall)" in body


def test_open_stall_posts_nothing_until_a_recording_finishes():
    body = function_body()
    assert "WHERE recovered_at IS NULL" in body
    assert "IF NOT coalesce(v_last_done > v_open.stalled_since, false) THEN" in body


def test_posts_through_the_ops_webhook_and_skips_the_row_without_it():
    body = function_body()
    assert "WHERE name = 'ops_alerts_slack_webhook'" in body
    assert body.count("PERFORM net.http_post(") == 1
    missing = body.index("IF v_url IS NULL THEN")
    assert body.index("RETURN", missing) < body.index("INSERT INTO public.stage1_stall_alerts", missing)


def test_only_cron_and_service_role_may_call_it():
    text = sql()
    assert f"REVOKE EXECUTE ON FUNCTION {SIGNATURE} FROM public, anon, authenticated;" in text
    assert f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO service_role;" in text
    assert "ALTER TABLE public.stage1_stall_alerts ENABLE ROW LEVEL SECURITY;" in text


def test_scheduled_every_15_minutes_off_the_other_jobs_minutes():
    match = re.search(r"cron\.schedule\('check_stage1_stall', '([^']+)'", sql())
    assert match and match.group(1) == "4,19,34,49 * * * *"
    assert "IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN" in sql()
