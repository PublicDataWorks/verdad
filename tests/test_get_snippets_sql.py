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
LOOSE_LABEL_SQL = REPO_ROOT / "supabase" / "database" / "sql" / "create_apply_and_upvote_label_function.sql"

# The latest migration that defines get_snippets; the loose file must match it.
GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20261118100000_research_view.sql"
LATEST_GET_SNIPPETS_MIGRATION = GET_SNIPPETS_MIGRATION
VER_387_GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20260921000400_get_snippets_denormalized_location.sql"
# VER-466 feed line (95+, or 90-94 analysed by gemini-3.* and reviewed): the body the research view starts from.
FEED_LINE90_GET_SNIPPETS_MIGRATION = MIGRATIONS_DIR / "20261109120100_feed_line90_functions.sql"
RESEARCH_INDEX_MIGRATION = MIGRATIONS_DIR / "20261118100100_research_rhetoric_index.sql"
APPLIED_VERSIONS = MIGRATIONS_DIR / "applied_versions.txt"

VER_387_MIGRATIONS = [
    MIGRATIONS_DIR / "20260921000100_snippets_location_columns_and_triggers.sql",
    MIGRATIONS_DIR / "20260921000200_snippets_location_backfill.sql",
    MIGRATIONS_DIR / "20260921000300_snippets_visible_location_indexes.sql",
    VER_387_GET_SNIPPETS_MIGRATION,
]

# The VER-466 feed predicate, as function_definition() returns it (one stripped line per source line).
FEED_LINE = (
    "s.status = 'Processed' AND (s.confidence_scores->>'overall')::INTEGER >= 90",
    "AND ((s.confidence_scores->>'overall')::INTEGER >= 95",
    "OR (s.analyzed_by LIKE 'gemini-3.%' AND s.reviewed_at IS NOT NULL))",
)
RHETORIC_SCORE = "(s.confidence_scores->'harmful_rhetoric'->>'score')::INTEGER >= 70"
RESEARCH_LABEL_IDS = (
    "ed57c3a2-d010-48f0-bf0b-9c1c1ca8d3ec",
    "7e9fa7e4-b11c-45a8-9dc7-1acf1b307056",
    "ff87ca7f-ac26-4859-af93-a585c0acdaf8",
)
LABEL_START = "CREATE OR REPLACE FUNCTION public.create_apply_and_upvote_label("

START = "CREATE OR REPLACE FUNCTION public.get_snippets("
END = "$function$;"


def function_definition(path, start_marker=START):
    """The CREATE OR REPLACE ... $function$; block, normalised to one stripped line per line."""
    sql = path.read_text()
    start = sql.index(start_marker)
    end = sql.index(END, start) + len(END)
    return [line.strip() for line in sql[start:end].splitlines()]


def test_ver_387_migration_files_exist():
    missing = [path.name for path in VER_387_MIGRATIONS if not path.is_file()]
    assert not missing, f"missing migration files: {missing}"


def test_migration_and_loose_sql_define_the_same_function():
    from_migration = function_definition(LATEST_GET_SNIPPETS_MIGRATION)
    from_loose = function_definition(LOOSE_SQL)
    assert from_migration == from_loose, (
        f"{LATEST_GET_SNIPPETS_MIGRATION.name} and {LOOSE_SQL.name} define different get_snippets bodies; "
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
    # Diff against the VER-466 body it starts from: the feed WHERE is rewritten into two branches and the research
    # inputs are added; nothing else moves. Compared as multisets so difflib's alignment of repeated lines
    # ("END IF;", the feed line that now appears in both branches) cannot change the result.
    from collections import Counter

    before = Counter(line for line in function_definition(FEED_LINE90_GET_SNIPPETS_MIGRATION) if line)
    after = Counter(line for line in function_definition(GET_SNIPPETS_MIGRATION) if line)
    removed = before - after
    added = Counter({line: n for line, n in (after - before).items() if not line.startswith("--")})
    assert removed == Counter([f"WHERE {FEED_LINE[0]}", FEED_LINE[2]])
    assert added == Counter(
        [
            "research_view BOOLEAN := COALESCE(p_filter->>'view', '') = 'research';",
            "research_snippet_ids UUID[];",
            "IF research_view THEN",
            "research_snippet_ids := ARRAY(",
            "SELECT DISTINCT sl.snippet",
            "FROM snippet_labels sl",
            "JOIN labels l ON l.id = sl.label",
            'JOIN public.user_roles ur ON ur."user" = sl.applied_by',
            "JOIN public.roles r ON r.id = ur.role",
            "WHERE l.is_research AND r.name = 'admin'",
            ");",
            "END IF;",
            "WHERE (",
            f"(NOT research_view AND {FEED_LINE[0]}",
            f"{FEED_LINE[2]})",
            "OR (research_view AND s.status = 'Processed' AND (",
            "((s.confidence_scores->>'overall')::INTEGER >= 90",
            FEED_LINE[1],
            f"{FEED_LINE[2]})",
            "OR s.id = ANY(research_snippet_ids)",
            f"OR {RHETORIC_SCORE}",
            "))",
            ")",
        ]
    )


def test_default_branch_is_the_feed_predicate_gated_on_research_view():
    # With research_view = FALSE the first branch must reduce to exactly the VER-466 feed predicate, so the
    # idx_snippets_feed* partial indexes keep matching the default feed.
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    assert f"(NOT research_view AND {FEED_LINE[0]}\n{FEED_LINE[1]}\n{FEED_LINE[2]})" in definition
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


def test_research_labels_are_seeded_by_id_never_by_text():
    # Security review: any logged-in user can create a label with any text, so a text match must not grant
    # research status. The seed names the three production ids and nothing else.
    sql = GET_SNIPPETS_MIGRATION.read_text()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    update = statements[statements.index("UPDATE public.labels") : statements.index("RESET lock_timeout;")]
    assert "SET is_research = true" in update
    assert "WHERE id IN (" in update
    for label_id in RESEARCH_LABEL_IDS:
        assert f"'{label_id}'" in update
    assert "LIKE" not in update.upper()
    assert "text" not in update.replace("is_research", "")
    assert statements.count("is_research = true") == 1, "is_research must only be set by the id-based seed"


def test_research_view_counts_only_admin_applied_research_labels():
    # Security review: any logged-in user can apply an existing label to any snippet, so the research view
    # trusts a research label only when snippet_labels.applied_by is an admin.
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION))
    start = definition.index("research_snippet_ids := ARRAY(")
    block = definition[start : definition.index("END IF;", start)]
    assert 'JOIN public.user_roles ur ON ur."user" = sl.applied_by' in block
    assert "JOIN public.roles r ON r.id = ur.role" in block
    assert "WHERE l.is_research AND r.name = 'admin'" in block
    # the only code that reads research labels is that admin-filtered array
    code = [line for line in definition.splitlines() if not line.startswith("--")]
    assert sum("is_research" in line for line in code) == 1


def test_label_write_path_refuses_research_labels_for_non_admins():
    definition = "\n".join(function_definition(GET_SNIPPETS_MIGRATION, LABEL_START))
    guard = definition.index("RAISE EXCEPTION 'Only admins can apply a research label';")
    insert = definition.index("INSERT INTO public.snippet_labels (snippet, label, applied_by)")
    assert guard < insert, "the guard must run before the snippet_labels insert"
    assert "IF EXISTS (SELECT 1 FROM public.labels WHERE id = label_id AND is_research)" in definition
    assert 'WHERE ur."user" = current_user_id AND r.name = \'admin\'' in definition
    # CREATE OR REPLACE drops settings it does not restate; keep the VER-372 pin
    assert "SET search_path = public, extensions, pg_temp" in definition
    assert "SECURITY DEFINER" in definition


def test_label_write_path_loose_sql_matches_the_migration():
    assert function_definition(GET_SNIPPETS_MIGRATION, LABEL_START) == function_definition(
        LOOSE_LABEL_SQL, LABEL_START
    ), f"{LOOSE_LABEL_SQL.name} and {GET_SNIPPETS_MIGRATION.name} define different create_apply_and_upvote_label bodies"


def test_research_labelled_snippets_get_a_location_backfill():
    # Research rows below 95 written before 2026-09-21 have NULL location columns (20260921000200 only
    # filled visible rows); without this, a states/sources filter hides them in the research view.
    sql = GET_SNIPPETS_MIGRATION.read_text()
    statements = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    backfill = statements[statements.index("UPDATE public.snippets s") : statements.index(START)]
    assert "SET location_state = a.location_state," in backfill
    assert "radio_station_code = a.radio_station_code" in backfill
    assert "s.radio_station_code IS NULL" in backfill
    for label_id in RESEARCH_LABEL_IDS:
        assert f"'{label_id}'" in backfill
    assert statements.index("RESET lock_timeout;") < statements.index("UPDATE public.snippets s")
