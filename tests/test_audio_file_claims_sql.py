"""fetch_a_new_audio_file_and_reserve_it lives in a migration and in loose SQL; both must match (VER-461)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261106100000_audio_file_flow_run_claims.sql"
INDEX_MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261106130000_audio_file_flow_run_claims_index.sql"
LOOSE_SQL = REPO_ROOT / "supabase" / "database" / "sql" / "fetch_a_new_audio_file_and_reserve_it.sql"

START = "CREATE OR REPLACE FUNCTION public.fetch_a_new_audio_file_and_reserve_it("
END = "$function$;"


def function_definition(path):
    sql = path.read_text()
    start = sql.index(START)
    end = sql.index(END, start) + len(END)
    return [line.strip() for line in sql[start:end].splitlines()]


def test_migration_and_loose_sql_define_the_same_function():
    assert function_definition(MIGRATION) == function_definition(LOOSE_SQL), (
        f"{MIGRATION.name} and {LOOSE_SQL.name} define different reserve bodies; change both "
        "(see .claude/rules/supabase-sql.md)"
    )


def test_reserve_stamps_the_claiming_flow_run_in_one_statement():
    definition = function_definition(MIGRATION)
    assert "SET status = 'Processing', claimed_by_flow_run = p_flow_run_id" in definition
    assert "FOR UPDATE SKIP LOCKED" in definition


def test_sweep_marks_stuck_files_with_a_response_processed():
    sql = MIGRATION.read_text()
    start = sql.index("CREATE OR REPLACE FUNCTION public.sweep_stuck_audio_files(")
    sweep = sql[start : sql.index(END, start)]
    assert "SET status = 'Processed'" in sweep
    assert "AND EXISTS (SELECT 1 FROM public.stage_1_llm_responses r WHERE r.audio_file = a.id)" in sweep


def test_release_filter_has_a_partial_index():
    # Without it each release UPDATE seq-scans audio_files and the hook hits the 8 s statement timeout (VER-463)
    sql = INDEX_MIGRATION.read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audio_files_processing_claimed_by_flow_run" in sql
    assert "ON public.audio_files (claimed_by_flow_run)" in sql
    assert "WHERE status = 'Processing';" in sql


def test_old_zero_argument_reserve_is_dropped():
    # Keeping it next to the new one makes the no-argument PostgREST call ambiguous
    assert "DROP FUNCTION IF EXISTS public.fetch_a_new_audio_file_and_reserve_it();" in MIGRATION.read_text()
