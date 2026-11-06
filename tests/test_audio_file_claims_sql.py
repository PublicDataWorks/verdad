"""fetch_a_new_audio_file_and_reserve_it lives in a migration and in loose SQL; both must match (VER-461)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261106100000_audio_file_flow_run_claims.sql"
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


def test_old_zero_argument_reserve_is_dropped():
    # Keeping it next to the new one makes the no-argument PostgREST call ambiguous
    assert "DROP FUNCTION IF EXISTS public.fetch_a_new_audio_file_and_reserve_it();" in MIGRATION.read_text()
