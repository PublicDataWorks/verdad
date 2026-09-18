"""Checks on supabase/migrations/ file naming and on the generated baseline.

A migration's version is the leading digits of its filename, and Supabase stores that version as the primary
key of supabase_migrations.schema_migrations. Two files that parse to the same version make `supabase db push`
fail, which is what four bare-date files in this repo used to do, so the naming is worth a test.

Every version below the baseline must be a comment-only placeholder: the baseline is the whole schema, and a
real statement before it (the 2024 dump once was one) would leave a fresh database half-built and then break.
"""

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
BASELINE = "20260915000000_baseline_public_schema.sql"
MANIFEST = MIGRATIONS_DIR / "applied_versions.txt"
FILENAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

# The one version production recorded with an 8-digit stamp. The file has to keep that exact version for
# `supabase migration list` to match the database; new files must use a full 14-digit timestamp.
LEGACY_SHORT_VERSIONS = {"20250225_alter_title_jsonb.sql"}


def migration_files():
    return sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))


def version_of(name):
    return name.split("_", 1)[0]


def pre_baseline_files():
    return [name for name in migration_files() if version_of(name) < version_of(BASELINE)]


def manifest_versions():
    lines = MANIFEST.read_text().splitlines()
    return {line.split("\t", 1)[0] for line in lines if line.strip() and not line.startswith("#")}


def test_migrations_directory_is_not_empty():
    assert migration_files(), f"no .sql files in {MIGRATIONS_DIR}"


@pytest.mark.parametrize("name", migration_files())
def test_filename_is_a_timestamped_migration(name):
    if name in LEGACY_SHORT_VERSIONS:
        assert re.fullmatch(r"^\d{8}_[a-z0-9_]+\.sql$", name)
        return
    assert FILENAME_RE.fullmatch(name), (
        f"{name} must be named YYYYMMDDHHMMSS_short_name.sql; a bare date collides with every other file "
        "sharing it once supabase db push parses the version"
    )


def test_versions_are_unique():
    versions = [version_of(name) for name in migration_files()]
    duplicates = sorted({v for v in versions if versions.count(v) > 1})
    assert not duplicates, f"duplicate migration versions: {duplicates}"


def test_baseline_exists_and_defines_the_core_tables():
    baseline = MIGRATIONS_DIR / BASELINE
    assert baseline.is_file(), f"{BASELINE} is missing"
    sql = baseline.read_text()
    assert sql.strip(), f"{BASELINE} is empty"
    for table in ("snippets", "audio_files"):
        assert re.search(
            rf"CREATE TABLE (IF NOT EXISTS )?public\.{table}\b", sql
        ), f"{BASELINE} has no CREATE TABLE for {table}"


@pytest.mark.parametrize("name", pre_baseline_files())
def test_pre_baseline_files_are_comment_only(name):
    statements = [
        line for line in (MIGRATIONS_DIR / name).read_text().splitlines() if line.strip() and not line.lstrip().startswith("--")
    ]
    assert not statements, f"{name} sorts before the baseline and must be comment-only; found: {statements[0]!r}"


def test_baseline_refuses_a_database_that_already_has_the_schema():
    sql = (MIGRATIONS_DIR / BASELINE).read_text()
    assert "to_regclass('public.snippets') IS NOT NULL" in sql and "RAISE EXCEPTION" in sql


def test_manifest_and_files_agree():
    versions = {version_of(name) for name in migration_files()}
    manifest = manifest_versions()
    assert manifest, f"{MANIFEST.name} is empty"
    # Files newer than the baseline may be pending (not yet applied to production); older ones must be recorded.
    pending = {v for v in versions - manifest if v > version_of(BASELINE)}
    assert versions - manifest - pending == set(), f"pre-baseline files missing from the manifest: {sorted(versions - manifest - pending)}"
    assert manifest - versions == set(), f"manifest versions without a file: {sorted(manifest - versions)}"


# --- News ledger (VER-367) ---------------------------------------------------------------------
# The migration ships unapplied on purpose: a human applies it in the Supabase SQL editor and only then
# records its version in applied_versions.txt.

NEWS_INDEX = "20260918000000_news_index.sql"
LOOSE_SQL = MIGRATIONS_DIR.parent / "database" / "sql" / "search_news_index.sql"


def test_news_index_migration_creates_the_ledger_and_its_search_function():
    sql = (MIGRATIONS_DIR / NEWS_INDEX).read_text()
    for table in ("news_index", "news_index_embeddings"):
        assert re.search(rf"CREATE TABLE (IF NOT EXISTS )?public\.{table}\b", sql), f"no CREATE TABLE for {table}"
    assert "CREATE OR REPLACE FUNCTION search_news_index(" in sql
    assert "sub_vector(embedding, 512)" in sql, "the HNSW index must be built on the 512-dim sub-vector"
    assert "ENABLE ROW LEVEL SECURITY" in sql


def test_news_index_migration_is_not_recorded_as_applied():
    assert version_of(NEWS_INDEX) not in manifest_versions(), (
        f"{NEWS_INDEX} has not been applied to production; do not add it to {MANIFEST.name} until it has"
    )


def test_search_news_index_is_also_kept_as_a_loose_sql_file():
    sql = LOOSE_SQL.read_text()
    assert "CREATE OR REPLACE FUNCTION search_news_index(" in sql
    assert NEWS_INDEX in sql, "the loose copy must point at the migration it mirrors"
