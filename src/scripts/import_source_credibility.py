#!/usr/bin/env python3
"""Sync the source credibility CSVs with their Supabase tables (VER-360).

Usage:
    python src/scripts/import_source_credibility.py import [--table domains|stations|all] [--dry-run] [--updated-by me]
    python src/scripts/import_source_credibility.py export [--table ...] [--out-dir data/source_credibility]
    python src/scripts/import_source_credibility.py diff   [--table ...]

``import`` upserts CSV rows on ``domain`` / ``station_code`` (existing table rows not in the CSV are left alone),
``export`` writes the tables back to CSV so admin edits can be committed, ``diff`` prints what import would change.
Requires SUPABASE_URL and SUPABASE_KEY (service role) except for ``--dry-run`` validation.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from processing_pipeline.source_credibility import (  # noqa: E402
    DOMAIN_COLUMNS,
    DOMAINS_CSV,
    STATION_COLUMNS,
    STATIONS_CSV,
    normalize_domain,
    read_csv_rows,
    validate_domain_row,
    validate_station_row,
)

load_dotenv()

TABLES = {
    "domains": {
        "table": "source_credibility_domains",
        "key": "domain",
        "columns": DOMAIN_COLUMNS,
        "csv": DOMAINS_CSV,
        "validate": validate_domain_row,
    },
    "stations": {
        "table": "source_provenance",
        "key": "station_code",
        "columns": STATION_COLUMNS,
        "csv": STATIONS_CSV,
        "validate": validate_station_row,
    },
}


def load_and_validate(kind: str, path: str | None = None) -> list[dict]:
    """Read one CSV, normalise keys and coerce types; raise ValueError listing every invalid row."""
    spec = TABLES[kind]
    rows = read_csv_rows(path or spec["csv"])
    problems = []
    seen = set()
    for line, row in enumerate(rows, start=2):
        missing = [c for c in spec["columns"] if c not in row]
        if missing:
            raise ValueError(f"{kind} CSV is missing columns: {missing}")
        errors = spec["validate"](row)
        key = row[spec["key"]]
        if key in seen:
            errors.append(f"duplicate {spec['key']} '{key}'")
        seen.add(key)
        if errors:
            problems.append(f"line {line} ({key!r}): " + "; ".join(errors))
    if problems:
        raise ValueError(f"{len(problems)} invalid {kind} row(s):\n  " + "\n  ".join(problems))
    return [coerce_row(kind, row) for row in rows]


def coerce_row(kind: str, row: dict) -> dict:
    spec = TABLES[kind]
    clean = {column: (row.get(column) or "").strip() or None for column in spec["columns"]}
    if kind == "domains":
        clean["domain"] = normalize_domain(clean["domain"])
        clean["tier"] = int(clean["tier"])
    else:
        clean["station_code"] = clean["station_code"].upper()
    return clean


def _comparable(kind: str, row: dict) -> dict:
    return coerce_row(
        kind, {column: "" if row.get(column) is None else str(row.get(column)) for column in TABLES[kind]["columns"]}
    )


def diff_rows(kind: str, csv_rows: list[dict], db_rows: list[dict]) -> dict:
    """Return {"added": [...], "changed": [(key, {column: (db, csv)})], "only_in_db": [...]}."""
    key = TABLES[kind]["key"]
    db_by_key = {_comparable(kind, row)[key]: _comparable(kind, row) for row in db_rows}
    added, changed = [], []
    for row in csv_rows:
        existing = db_by_key.pop(row[key], None)
        if existing is None:
            added.append(row[key])
            continue
        deltas = {c: (existing[c], row[c]) for c in TABLES[kind]["columns"] if existing[c] != row[c]}
        if deltas:
            changed.append((row[key], deltas))
    return {"added": added, "changed": changed, "only_in_db": sorted(db_by_key)}


def _client():
    supabase_url, supabase_key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
    from supabase import create_client

    return create_client(supabase_url, supabase_key)


def fetch_table(client, kind: str) -> list[dict]:
    return client.table(TABLES[kind]["table"]).select("*").order(TABLES[kind]["key"]).execute().data or []


def import_table(client, kind: str, rows: list[dict], updated_by: str, dry_run: bool) -> None:
    spec = TABLES[kind]
    diff = (
        diff_rows(kind, rows, fetch_table(client, kind))
        if client
        else {"added": [r[spec["key"]] for r in rows], "changed": [], "only_in_db": []}
    )
    print_diff(kind, diff)
    if dry_run:
        print(f"  dry run: {len(rows)} {kind} rows validated, nothing written")
        return
    stamp = datetime.now(timezone.utc).isoformat()
    payload = [{**row, "updated_at": stamp, "updated_by": updated_by} for row in rows]
    client.table(spec["table"]).upsert(payload, on_conflict=spec["key"]).execute()
    print(f"  upserted {len(payload)} {kind} rows into {spec['table']}")


def export_table(client, kind: str, out_dir: str) -> str:
    spec = TABLES[kind]
    rows = fetch_table(client, kind)
    path = os.path.join(out_dir, os.path.basename(spec["csv"]))
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(spec["columns"]))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: "" if row.get(column) is None else row.get(column) for column in spec["columns"]})
    print(f"  wrote {len(rows)} {kind} rows to {path}")
    return path


def print_diff(kind: str, diff: dict) -> None:
    print(
        f"{kind}: {len(diff['added'])} to add, {len(diff['changed'])} to change, {len(diff['only_in_db'])} only in table"
    )
    for key in diff["added"]:
        print(f"  + {key}")
    for key, deltas in diff["changed"]:
        rendered = ", ".join(f"{column}: {old!r} -> {new!r}" for column, (old, new) in deltas.items())
        print(f"  ~ {key}: {rendered}")
    for key in diff["only_in_db"]:
        print(f"  = {key} (in table only; left unchanged)")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Import/export/diff the source credibility tables")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("import", "export", "diff"):
        p = sub.add_parser(name)
        p.add_argument("--table", choices=["domains", "stations", "all"], default="all")
    sub.choices["import"].add_argument("--dry-run", action="store_true", help="Validate and show the diff only")
    sub.choices["import"].add_argument("--updated-by", default=os.getenv("USER", "import_script"))
    sub.choices["export"].add_argument("--out-dir", default=os.path.dirname(DOMAINS_CSV))
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    kinds = ["domains", "stations"] if args.table == "all" else [args.table]

    if args.command == "import":
        rows_by_kind = {kind: load_and_validate(kind) for kind in kinds}  # validate everything before any write
        client = None
        if not args.dry_run or (os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")):
            client = _client()
        for kind in kinds:
            import_table(client, kind, rows_by_kind[kind], args.updated_by, args.dry_run)
    elif args.command == "export":
        client = _client()
        os.makedirs(args.out_dir, exist_ok=True)
        for kind in kinds:
            export_table(client, kind, args.out_dir)
    elif args.command == "diff":
        client = _client()
        for kind in kinds:
            print_diff(kind, diff_rows(kind, load_and_validate(kind), fetch_table(client, kind)))


if __name__ == "__main__":
    main()
