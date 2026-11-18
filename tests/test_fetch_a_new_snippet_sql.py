"""fetch_a_new_snippet_and_reserve_it lives in a migration and in loose SQL; both must match (VER-454)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261113100000_snippet_flow_run_claims.sql"
LOOSE_SQL = REPO_ROOT / "supabase" / "database" / "sql" / "fetch_a_new_snippet_and_reserve_it.sql"

START = "CREATE OR REPLACE FUNCTION public.fetch_a_new_snippet_and_reserve_it("
RELEASE_START = "CREATE OR REPLACE FUNCTION public.release_flow_run_snippets("
END = "$function$;"


def function_definition(path, start_marker=START):
    sql = path.read_text()
    start = sql.index(start_marker)
    end = sql.index(END, start) + len(END)
    return [line.strip() for line in sql[start:end].splitlines()]


def test_migration_and_loose_sql_define_the_same_function():
    assert function_definition(MIGRATION) == function_definition(LOOSE_SQL), (
        f"{MIGRATION.name} and {LOOSE_SQL.name} define different reserve bodies; change both "
        "(see .claude/rules/supabase-sql.md)"
    )


def test_reserve_orders_by_priority_then_recency():
    definition = function_definition(MIGRATION)
    assert "ORDER BY priority DESC, recorded_at DESC" in definition
    assert "FOR UPDATE SKIP LOCKED" in definition


def test_reserve_stamps_the_claiming_flow_run_in_one_statement():
    assert "SET status = 'Processing', claimed_by_flow_run = p_flow_run_id" in function_definition(MIGRATION)


def test_old_zero_argument_reserve_is_dropped():
    # Keeping it next to the new one makes the no-argument PostgREST call ambiguous
    assert "DROP FUNCTION IF EXISTS public.fetch_a_new_snippet_and_reserve_it();" in MIGRATION.read_text()


def test_release_requeues_only_the_run_clips_still_processing():
    release = function_definition(MIGRATION, RELEASE_START)
    assert "WHERE s.claimed_by_flow_run = p_flow_run_id" in release
    assert "AND s.status = 'Processing';" in release


def test_release_stops_a_clip_that_keeps_crashing_its_run():
    release = function_definition(MIGRATION, RELEASE_START)
    assert "SET status = 'New', analysis_attempts = s.analysis_attempts + p_count_attempt::integer" in release
    assert "AND p_count_attempt" in release
    assert "AND s.analysis_attempts >= p_max_attempts;" in release
