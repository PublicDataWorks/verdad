"""fetch_a_new_snippet_and_reserve_it lives in a migration and in loose SQL; both must match (VER-454)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATION = REPO_ROOT / "supabase" / "migrations" / "20261104100000_stage3_snippet_priority.sql"
LOOSE_SQL = REPO_ROOT / "supabase" / "database" / "sql" / "fetch_a_new_snippet_and_reserve_it.sql"

START = "CREATE OR REPLACE FUNCTION public.fetch_a_new_snippet_and_reserve_it()"
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


def test_reserve_orders_by_priority_then_recency():
    definition = function_definition(MIGRATION)
    assert "ORDER BY priority DESC, recorded_at DESC" in definition
    assert "FOR UPDATE SKIP LOCKED" in definition
