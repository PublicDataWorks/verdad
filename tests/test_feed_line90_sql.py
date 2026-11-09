"""VER-466: the per-model feed line must read the same in Stage 3, the feed functions and the partial indexes."""

import re
from pathlib import Path

from processing_pipeline.constants import CONFIDENCE_THRESHOLD, GEMINI_3_CONFIDENCE_THRESHOLD, GEMINI_3_PREFIX

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
INDEX_SQL = (MIGRATIONS_DIR / "20261109120000_feed_line90_indexes.sql").read_text()
FUNCTIONS_SQL = (MIGRATIONS_DIR / "20261109120100_feed_line90_functions.sql").read_text()

INDEX_PREDICATE = f"""WHERE (status = 'Processed'::processing_status
           AND ((confidence_scores ->> 'overall'::text))::integer >= {GEMINI_3_CONFIDENCE_THRESHOLD}
           AND ((((confidence_scores ->> 'overall'::text))::integer >= {CONFIDENCE_THRESHOLD})
                OR (analyzed_by LIKE '{GEMINI_3_PREFIX}%' AND reviewed_at IS NOT NULL)));"""
FUNCTION_PREDICATE = (
    f"(s.confidence_scores->>'overall')::INTEGER >= {GEMINI_3_CONFIDENCE_THRESHOLD}",
    f"AND ((s.confidence_scores->>'overall')::INTEGER >= {CONFIDENCE_THRESHOLD}",
    f"OR (s.analyzed_by LIKE '{GEMINI_3_PREFIX}%' AND s.reviewed_at IS NOT NULL))",
)
LIVE_LINE_95_INDEXES = 6


def index_statements():
    return [stmt for stmt in INDEX_SQL.split(";") if "CREATE INDEX" in stmt]


def function_predicate_count(sql):
    lines = [line.strip() for line in sql.splitlines()]
    return sum(
        1
        for i, line in enumerate(lines)
        if line.endswith(FUNCTION_PREDICATE[0]) and tuple(lines[i + 1 : i + 3]) == FUNCTION_PREDICATE[1:]
    )


def test_every_feed_index_carries_the_full_visible_predicate():
    statements = index_statements()
    assert len(statements) == LIVE_LINE_95_INDEXES
    for stmt in statements:
        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_snippets_feed" in stmt
        assert INDEX_PREDICATE.rstrip(";") in stmt


def test_index_migration_warns_about_transactions():
    assert "OUTSIDE a transaction" in INDEX_SQL
    assert "indisvalid" in INDEX_SQL
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in INDEX_SQL


def test_every_feed_function_predicate_is_the_per_model_line():
    # get_snippets 1, get_topic_details 3, get_trending_topics 1; no bare 95 line left
    assert function_predicate_count(FUNCTIONS_SQL) == 5
    assert len(re.findall(r">= 95\b", FUNCTIONS_SQL)) == 5


def test_function_and_index_predicates_match():
    def normalise(text):
        text = re.sub(r"\bs\.|::text|::processing_status|\s+|[()]", "", text)
        return text.lower()

    function_clause = "status = 'Processed' AND " + " ".join(FUNCTION_PREDICATE)
    assert normalise(function_clause) == normalise(INDEX_PREDICATE.removeprefix("WHERE").rstrip(";"))


def test_both_get_snippets_branches_select_the_review_columns():
    assert FUNCTIONS_SQL.count("s.status, s.confidence_scores, s.analyzed_by, s.reviewed_at,") == 2


def test_landing_page_and_statistics_keep_their_line():
    assert "FUNCTION public.get_landing_page_content" not in FUNCTIONS_SQL
    assert "FUNCTION public.get_statistics" not in FUNCTIONS_SQL


def test_security_definer_functions_pin_search_path():
    for match in re.finditer(r"SECURITY DEFINER", FUNCTIONS_SQL):
        window = FUNCTIONS_SQL[match.start() : FUNCTIONS_SQL.index("AS $", match.start())]
        assert "SET search_path = public, extensions, pg_temp" in window
