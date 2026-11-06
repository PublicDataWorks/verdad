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

# The latest migration that defines get_snippets; the loose file must match it.
GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20261106100000_research_view.sql"
VER_387_GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20260921000400_get_snippets_denormalized_location.sql"
RESEARCH_INDEX_MIGRATION = MIGRATIONS_DIR / "20261106100100_research_rhetoric_index.sql"
APPLIED_VERSIONS = MIGRATIONS_DIR / "applied_versions.txt"

VER_387_MIGRATIONS = [
    MIGRATIONS_DIR / "20260921000100_snippets_location_columns_and_triggers.sql",
    MIGRATIONS_DIR / "20260921000200_snippets_location_backfill.sql",
    MIGRATIONS_DIR / "20260921000300_snippets_visible_location_indexes.sql",
    VER_387_GET_SNIPPETS_MIGRATION,
]

OLD_VISIBILITY = "WHERE s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95"
RHETORIC_SCORE = "(s.confidence_scores->'harmful_rhetoric'->>'score')::INTEGER >= 70"

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
    for path in [*VER_387_MIGRATIONS, GET_SNIPPETS_MIGRATION]:
        sql = path.read_text()
        for match in re.finditer(r"SECURITY DEFINER", sql):
            window = sql[match.start() : sql.index("AS $", match.start())]
            assert "SET search_path = public, extensions, pg_temp" in window, (
                f"{path.name}: a SECURITY DEFINER function does not pin "
                "search_path = public, extensions, pg_temp"
            )


def test_ddl_migration_caps_lock_timeout():
    # ACCESS EXCLUSIVE on snippets and audio_files must not queue the feed behind a slow reader.
    lines = VER_387_MIGRATIONS[0].read_text().splitlines()
    statements = "\n".join(line for line in lines if not line.lstrip().startswith("--"))
    assert statements.index("SET lock_timeout = '3s';") < statements.index("ALTER TABLE")


def test_backfill_and_guard_cover_exactly_the_visible_rows():
    # Only visible rows are backfilled, so every write that can make a row visible must fill it.
    visible = "status = 'Processed'::processing_status\n            AND ((confidence_scores ->> 'overall'::text))::integer >= 95"
    columns_sql, backfill_sql, _, get_snippets_sql = (path.read_text() for path in VER_387_MIGRATIONS)
    assert "BEFORE INSERT OR UPDATE OF audio_file, status, confidence_scores ON public.snippets" in columns_sql
    assert visible.replace("confidence_scores", "s2.confidence_scores").replace("status =", "s2.status =") in backfill_sql
    assert visible.replace("\n            ", "\n          ") in get_snippets_sql


def test_concurrent_index_migration_warns_about_transactions():
    sql = (MIGRATIONS_DIR / "20260921000300_snippets_visible_location_indexes.sql").read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_state" in sql
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_visible_station" in sql
    assert "MUST be run OUTSIDE a transaction" in sql
    assert "indisvalid" in sql


# --- VER-462: research view -------------------------------------------------------------------


def test_research_view_changes_nothing_but_the_visibility_predicate_and_its_inputs():
    # Diff against the VER-387 body: only additions, plus the one visibility line that became two branches.
    import difflib

    before = function_definition(VER_387_GET_SNIPPETS_MIGRATION)
    after = function_definition(GET_SNIPPETS_MIGRATION)
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed += before[i1:i2]
        if tag in ("replace", "insert"):
            added += after[j1:j2]
    assert [line for line in removed if line] == [OLD_VISIBILITY]
    # Compared as a sorted list: difflib may align a repeated line such as "END IF;" with either copy.
    code = sorted(line for line in added if line and not line.startswith("--"))
    assert code == sorted([
        "research_view BOOLEAN := COALESCE(p_filter->>'view', '') = 'research';",
        "research_snippet_ids UUID[];",
        "IF research_view THEN",
        "research_snippet_ids := ARRAY(",
        "SELECT DISTINCT sl.snippet",
        "FROM snippet_labels sl",
        "JOIN labels l ON l.id = sl.label",
        "WHERE l.is_research",
        ");",
        "END IF;",
        "WHERE (",
        "(NOT research_view AND s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 95)",
        "OR (research_view AND s.status = 'Processed' AND (",
        "(s.confidence_scores->>'overall')::INTEGER >= 95",
        "OR s.id = ANY(research_snippet_ids)",
        f"OR {RHETORIC_SCORE}",
        "))",
        ")",
    ])


def test_default_branch_is_the_old_predicate_gated_on_research_view():
    # With research_view = FALSE the first branch must reduce to exactly the old predicate, so the
    # visible partial indexes keep matching the default feed.
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    old = OLD_VISIBILITY.removeprefix("WHERE ")
    assert f"(NOT research_view AND {old})" in definition
    assert "OR (research_view AND s.status = 'Processed' AND (" in definition
    # research_view is only ever set from p_filter.view, and only the literal 'research' turns it on
    assert definition.count("research_view :=") == 0
    assert "research_view BOOLEAN := COALESCE(p_filter->>'view', '') = 'research';" in definition


def test_research_view_returns_the_same_shape():
    # harmful_rhetoric rides inside confidence_scores; the projection is untouched.
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    assert "s.confidence_scores," in definition
    assert "'num_of_snippets', total_count" in definition
    assert "harmful_rhetoric" not in definition.split("paginated_snippets AS (")[1]


def test_research_view_migration_adds_and_seeds_is_research():
    sql = GET_SNIPPETS_MIGRATION.read_text()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    assert "ADD COLUMN IF NOT EXISTS is_research boolean NOT NULL DEFAULT false;" in statements
    assert "WHERE text LIKE 'Texas research 2026:%'" in statements
    assert statements.index("SET lock_timeout = '3s';") < statements.index("ALTER TABLE public.labels")
    assert statements.index("ALTER TABLE public.labels") < statements.index(START)
    assert "NOTIFY pgrst, 'reload schema';" in statements


def test_research_index_predicate_matches_the_function():
    # The planner can only use the partial index for the rhetoric arm when both say the same thing.
    sql = RESEARCH_INDEX_MIGRATION.read_text()
    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_research_rhetoric" in sql
    assert "ON public.snippets (recorded_at DESC, id DESC)" in sql
    assert "((confidence_scores -> 'harmful_rhetoric'::text) ->> 'score'::text)::integer >= 70" in sql
    assert "status = 'Processed'::processing_status" in sql
    assert "MUST be run OUTSIDE a transaction" in sql
    assert "indisvalid" in sql
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    assert "COALESCE((s.confidence_scores->'harmful_rhetoric'" not in definition


def test_research_view_migrations_are_not_marked_applied():
    applied = APPLIED_VERSIONS.read_text()
    for path in (GET_SNIPPETS_MIGRATION, RESEARCH_INDEX_MIGRATION):
        assert path.name.split("_", 1)[0] not in applied, f"{path.name} is not applied to production yet"
