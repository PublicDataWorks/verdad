"""Checks on supabase/migrations/ file naming and on the generated baseline.

A migration's version is the leading digits of its filename, and Supabase stores that version as the primary
key of supabase_migrations.schema_migrations. Two files that parse to the same version make `supabase db push`
fail, which is what four bare-date files in this repo used to do, so the naming is worth a test.
"""

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
BASELINE = "20260915000000_baseline_public_schema.sql"
FILENAME_RE = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")

# The one version production recorded with an 8-digit stamp. The file has to keep that exact version for
# `supabase migration list` to match the database; new files must use a full 14-digit timestamp.
LEGACY_SHORT_VERSIONS = {"20250225_alter_title_jsonb.sql"}


def migration_files():
    return sorted(path.name for path in MIGRATIONS_DIR.glob("*.sql"))


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
    versions = [name.split("_", 1)[0] for name in migration_files()]
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
