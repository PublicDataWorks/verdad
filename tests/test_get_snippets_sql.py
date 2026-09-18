"""Checks on the VER-387 get_snippets migrations (2026-09-21).

get_snippets lives in two places -- supabase/migrations/ and the loose supabase/database/sql/
directory -- and .claude/rules/supabase-sql.md says both must be changed together. Nothing applies
these files automatically, so a drift between them is only ever found by a human reading SQL; these
tests find it instead.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
LOOSE_SQL = REPO_ROOT / "supabase" / "database" / "sql" / "get_snippets_function.sql"

GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20260921000400_get_snippets_denormalized_location.sql"

VER_387_MIGRATIONS = [
    MIGRATIONS_DIR / "20260921000100_snippets_location_columns_and_triggers.sql",
    MIGRATIONS_DIR / "20260921000200_snippets_location_backfill.sql",
    MIGRATIONS_DIR / "20260921000300_snippets_visible_location_indexes.sql",
    GET_SNIPPETS_MIGRATION,
]

START = "CREATE OR REPLACE FUNCTION public.get_snippets("
END = "$function$;"


def function_definition(path):
    """The CREATE OR REPLACE ... $function$; block, normalised to one stripped line per line."""
    sql = path.read_text()
    start = sql.index(START)
    end = sql.index(END, start) + len(END)
    return [line.strip() for line in sql[start:end].splitlines()]


def test_ver_387_migration_files_exist():
    missing = [path.name for path in VER_387_MIGRATIONS if not path.is_file()]
    assert not missing, f"missing migration files: {missing}"


def test_migration_and_loose_sql_define_the_same_function():
    from_migration = function_definition(GET_SNIPPETS_MIGRATION)
    from_loose = function_definition(LOOSE_SQL)
    assert from_migration == from_loose, (
        f"{GET_SNIPPETS_MIGRATION.name} and {LOOSE_SQL.name} define different get_snippets bodies; "
        "change both (see .claude/rules/supabase-sql.md)"
    )


def test_definition_filters_on_the_denormalized_columns():
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    assert "s.location_state = ANY(state_codes)" in definition
    assert "s.radio_station_code = ANY(source_codes)" in definition
    assert "state_filtered_audio_ids" not in definition, "the audio_files filter CTE is still there"
    assert "source_filtered_audio_ids" not in definition


def test_definition_keeps_the_audio_files_projection():
    # The returned audio_file object must still come from audio_files; only the filter changed.
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    assert "'location_state', a.location_state" in definition
    assert "LEFT JOIN audio_files a ON s.audio_file = a.id" in definition


def test_security_definer_functions_pin_search_path():
    # VER-372: every SECURITY DEFINER function pins search_path, with pg_temp last.
    for path in VER_387_MIGRATIONS:
        sql = path.read_text()
        for match in re.finditer(r"SECURITY DEFINER", sql):
            window = sql[match.start() : sql.index("AS $", match.start())]
            assert "SET search_path = public, extensions, pg_temp" in window, (
                f"{path.name}: a SECURITY DEFINER function does not pin "
                "search_path = public, extensions, pg_temp"
            )


def test_concurrent_index_migration_warns_about_transactions():
    sql = (MIGRATIONS_DIR / "20260921000300_snippets_visible_location_indexes.sql").read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_state" in sql
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_station" in sql
    assert "MUST be run OUTSIDE a transaction" in sql
    assert "indisvalid" in sql
