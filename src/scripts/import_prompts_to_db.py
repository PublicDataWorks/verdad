#!/usr/bin/env python3
"""
Script to import prompt files into the database as versioned entries.

The list of prompt files per stage/sub_stage and the version each one is at live in
``prompts/manifest.json`` (see ``src/scripts/prompt_manifest.py``).

Usage:
    # Deploy whatever the manifest says differs from the active DB versions (used by CI on merge)
    python src/scripts/import_prompts_to_db.py import --from-manifest
    python src/scripts/import_prompts_to_db.py import --from-manifest --dry-run

    # Import every mapped entry (or --stages ...) at one explicit version
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --description "Initial import from files"
    python src/scripts/import_prompts_to_db.py import --version 1.1.0 --description "Updated Stage 3 prompt" --no-active
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --dry-run  # Preview changes without committing

    python src/scripts/import_prompts_to_db.py list [--active]
    python src/scripts/import_prompts_to_db.py diff  # Compare local files with active DB versions
    python src/scripts/import_prompts_to_db.py diff --stages stage_3 --show-diff
"""

import argparse
import difflib
import json
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from src.processing_pipeline.constants import PromptStage
from src.processing_pipeline.stage_1.constants import Stage1SubStage
from src.processing_pipeline.stage_4.constants import Stage4SubStage
from src.scripts.prompt_manifest import (
    FILE_TYPES,
    format_plan,
    load_manifest,
    manifest_files,
    plan_manifest_import,
    read_prompt_files,
    split_stage_label,
    stage_label,
    validate_version,
)

load_dotenv()

ALLOWED_PROMPT_DIR = "prompts"
MAX_DESCRIPTION_LENGTH = 500
MISSING_ENV_EXIT_CODE = 2


class MissingEnvError(RuntimeError):
    """SUPABASE_URL / SUPABASE_KEY are not set."""


SUB_STAGE_ENUMS = {
    PromptStage.STAGE_1: Stage1SubStage,
    PromptStage.STAGE_4: Stage4SubStage,
}


def _manifest_key(label: str):
    """Map a manifest label to the (PromptStage, sub-stage enum | None) tuple used by the pipeline."""
    stage_value, sub_stage_value = split_stage_label(label)
    stage = PromptStage(stage_value)
    if sub_stage_value is None:
        return (stage, None)
    return (stage, SUB_STAGE_ENUMS[stage](sub_stage_value))


MANIFEST = load_manifest()

# (stage, sub_stage) -> {file_type: path}. Derived from the manifest so there is one source of truth.
PROMPT_MAPPING = {_manifest_key(label): manifest_files(entry) for label, entry in MANIFEST.items()}


def validate_path_safety(path: str) -> bool:
    abs_path = os.path.realpath(path)
    abs_base = os.path.realpath(ALLOWED_PROMPT_DIR)
    return abs_path.startswith(abs_base + os.sep)


def validate_description(description: str) -> str:
    description = description.strip()
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(
            f"Description too long ({len(description)} chars). Maximum allowed: {MAX_DESCRIPTION_LENGTH} chars"
        )
    return description


def _stage_label(key):
    """Format a (stage, sub_stage) tuple as a display string."""
    stage, sub_stage = key
    return stage_label(stage.value, sub_stage.value if sub_stage else None)


def _parse_stage_label(label: str):
    """Parse a display string back to a (stage, sub_stage) tuple."""
    return _manifest_key(label) if label in MANIFEST else None


def check_files_exist(keys: list) -> tuple[bool, list[str], list[str]]:
    missing_files = []
    unsafe_paths = []
    for key in keys:
        if key not in PROMPT_MAPPING:
            continue
        files = PROMPT_MAPPING[key]
        label = _stage_label(key)
        for file_type, path in files.items():
            if not validate_path_safety(path):
                unsafe_paths.append(f"{label}/{file_type}: {path}")
            elif not os.path.exists(path):
                missing_files.append(f"{label}/{file_type}: {path}")
    return len(missing_files) == 0 and len(unsafe_paths) == 0, missing_files, unsafe_paths


def _validate_files(keys: list):
    _, missing_files, unsafe_paths = check_files_exist(keys)

    if unsafe_paths:
        print("Error: The following paths are outside the allowed directory:")
        for unsafe in unsafe_paths:
            print(f"  - {unsafe}")
        raise ValueError("Cannot proceed with unsafe file paths")

    if missing_files:
        print("Error: The following files are missing:")
        for missing in missing_files:
            print(f"  - {missing}")
        raise FileNotFoundError("Cannot proceed with missing files")


def _require_supabase_env():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_key:
        raise MissingEnvError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
    return supabase_url, supabase_key


def _create_client():
    return create_client(*_require_supabase_env())


def load_local_prompt(files: dict) -> dict | None:
    """Contents of one entry's prompt files (schema parsed as JSON), or None if any file is missing."""
    if not all(os.path.exists(path) for path in files.values()):
        return None
    return read_prompt_files({"files": files})


def _normalize_field(field: str, value):
    """Make local and database values comparable: NULL and "" text are equal, schemas are parsed JSON."""
    if field == "output_schema":
        return json.loads(value) if isinstance(value, str) else value
    return value or ""


def compare_prompt_entry(local: dict | None, db_row: dict | None) -> tuple[str, list[str]]:
    """
    Compare local prompt files with the active database row for one (stage, sub_stage).

    Pure function (no I/O). Returns (status, differing_fields), where status is one of
    "in sync", "differs", "no active version in db" or "missing local file".
    """
    if local is None:
        return "missing local file", []
    if db_row is None:
        return "no active version in db", []
    differing = [
        field
        for field in FILE_TYPES
        if _normalize_field(field, local.get(field)) != _normalize_field(field, db_row.get(field))
    ]
    return ("differs" if differing else "in sync"), differing


def fetch_active_prompts(client) -> dict:
    """Return the active prompt_versions rows keyed by (stage, sub_stage)."""
    response = (
        client.table("prompt_versions")
        .select("id, stage, sub_stage, version, description, created_at, " + ", ".join(FILE_TYPES))
        .eq("is_active", True)
        .execute()
    )
    return {(row["stage"], row["sub_stage"]): row for row in response.data or []}


def _field_text(field: str, value) -> str:
    text = value or ""
    if field == "output_schema":
        text = json.dumps(_normalize_field(field, value), indent=2, sort_keys=True)
    return text if text.endswith("\n") else text + "\n"


def print_field_diff(label: str, field: str, local_path: str, local_value, db_value):
    diff = difflib.unified_diff(
        _field_text(field, db_value).splitlines(keepends=True),
        _field_text(field, local_value).splitlines(keepends=True),
        fromfile=f"db:{label}/{field}",
        tofile=f"local:{local_path}",
    )
    sys.stdout.writelines(diff)
    print()


def diff_prompts(stages: list = None, show_diff: bool = False) -> int:
    """
    Compare local prompt files with the active database versions (read-only).

    Returns the exit code: 0 when everything is in sync, 1 on any drift, 2 on connection/config error.
    """
    keys = stages if stages else list(PROMPT_MAPPING.keys())

    try:
        active = fetch_active_prompts(_create_client())
    except Exception as e:
        print(f"Error: could not load active prompt versions: {e}", file=sys.stderr)
        return 2

    all_in_sync = True
    for key in keys:
        stage, sub_stage = key
        label = _stage_label(key)
        files = PROMPT_MAPPING[key]
        local = load_local_prompt(files)
        db_row = active.get((stage.value, sub_stage.value if sub_stage else None))
        status, differing = compare_prompt_entry(local, db_row)

        detail = f" ({', '.join(differing)})" if differing else ""
        created = (db_row.get("created_at") or "")[:10] if db_row else ""
        version = f" [db v{db_row['version']}, {created}]" if db_row else ""
        print(f"{label}: {status}{detail}{version}")
        if status != "in sync":
            all_in_sync = False
        if show_diff:
            for field in differing:
                print_field_diff(label, field, files.get(field, "<no local file>"), local.get(field), db_row.get(field))

    return 0 if all_in_sync else 1


def _import_one(client, key, version: str, description: str, set_active: bool, dry_run: bool) -> bool:
    """Import a single (stage, sub_stage) entry. Returns True on success (or dry run)."""
    stage, sub_stage = key
    label = _stage_label(key)
    print(f"Importing {label} v{version}...")

    data = read_prompt_files(MANIFEST[label])

    if dry_run:
        print(f"  Would create version {version} for {label}")
        print(f"    - System instruction: {len(data.get('system_instruction', '')) or 'N/A'} chars")
        print(f"    - User prompt: {len(data.get('user_prompt', '')) or 'N/A'} chars")
        print(f"    - Output schema: {'Yes' if data.get('output_schema') else 'No'}")
        if set_active:
            print("    - Would deactivate existing active version and set this as active")
        return True

    # Use PostgreSQL function for atomic insert + activation
    try:
        response = client.rpc(
            "upsert_prompt_version",
            {
                "p_stage": stage.value,
                "p_version": version,
                "p_description": description,
                "p_created_by": "import_script",
                "p_system_instruction": data.get("system_instruction"),
                "p_user_prompt": data.get("user_prompt"),
                "p_output_schema": data.get("output_schema"),
                "p_set_active": set_active,
                "p_sub_stage": sub_stage.value if sub_stage else None,
            },
        ).execute()
    except Exception as e:
        print(f"  Error creating prompt version for {label}: {e}")
        return False

    if not response.data:
        print(f"  Error: No data returned for {label}")
        return False

    print(f"  Created prompt version: {response.data['id']}")
    if set_active:
        print(f"  Set as active version for {label}")
    return True


def import_prompts(
    version: str,
    description: str,
    set_active: bool = True,
    stages: list = None,
    dry_run: bool = False,
) -> int:
    """
    Import prompt files into the database at one explicit version. Returns the number of entries that failed.

    Args:
        version: Version string (e.g., "1.0.0")
        description: Human-readable description of this version
        set_active: Whether to set these versions as active (default True)
        stages: Optional list of specific stages to import. If None, imports all.
        dry_run: If True, preview changes without committing to database.
    """
    if not validate_version(version):
        raise ValueError(f"Invalid version format: '{version}'. Must be semver format (e.g., 1.0.0)")

    description = validate_description(description)
    keys_to_import = stages if stages else list(PROMPT_MAPPING.keys())
    _validate_files(keys_to_import)

    if dry_run:
        print("\n=== DRY RUN MODE - No changes will be made ===\n")

    _require_supabase_env()
    client = None if dry_run else _create_client()

    success_count = 0
    error_count = 0

    for key in keys_to_import:
        if key not in PROMPT_MAPPING:
            print(f"Warning: Unknown key '{key}', skipping...")
            continue
        if _import_one(client, key, version, description, set_active, dry_run):
            success_count += 1
        else:
            error_count += 1

    if dry_run:
        print(f"\n=== DRY RUN COMPLETE - No changes were made ({len(keys_to_import)} entries previewed) ===")
    else:
        print(f"\nImport complete! Success: {success_count}, Errors: {error_count}")
    return error_count


def fetch_db_versions(client) -> list[dict]:
    response = client.table("prompt_versions").select("stage, sub_stage, version, is_active").execute()
    return response.data or []


def import_from_manifest(dry_run: bool = False) -> int:
    """
    Import (and activate) every manifest entry whose version differs from the active DB version.

    Returns the number of entries that failed (or that conflict with an existing inactive version).
    """
    _validate_files(list(PROMPT_MAPPING.keys()))
    client = _create_client()  # reads only until an import is needed

    actions = plan_manifest_import(MANIFEST, fetch_db_versions(client))
    if dry_run:
        print("\n=== DRY RUN MODE - No changes will be made ===\n")
    print(format_plan(actions))
    print()

    to_import = [a for a in actions if a.action == "import"]
    conflicts = [a for a in actions if a.action == "conflict"]
    for a in conflicts:
        print(f"Conflict: {a.label}: {a.reason}")

    error_count = len(conflicts)
    success_count = 0
    for a in to_import:
        description = validate_description(MANIFEST[a.label].get("description") or "Imported from manifest")
        if _import_one(client, _manifest_key(a.label), a.manifest_version, description, True, dry_run):
            success_count += 1
        else:
            error_count += 1

    up_to_date = len(actions) - len(to_import) - len(conflicts)
    verb = "Would import" if dry_run else "Imported"
    noun = "entry" if success_count == 1 else "entries"
    print(f"\n{verb} {success_count} {noun}; {up_to_date} up to date; {error_count} error(s).")
    return error_count


def list_versions(active_only: bool = False):
    """List prompt versions in the database."""
    client = _create_client()

    query = client.table("prompt_versions").select("id, stage, sub_stage, version, is_active, description, created_at")
    if active_only:
        query = query.eq("is_active", True)
    response = query.order("stage").order("sub_stage").order("created_at", desc=True).execute()

    if not response.data:
        print("No prompt versions found in database.")
        return

    print("\nPrompt Versions:")
    print("-" * 120)
    print(f"{'Stage':<15} {'Sub Stage':<30} {'Version':<10} {'Active':<8} {'Description':<30}")
    print("-" * 120)

    for row in response.data:
        active = "Yes" if row["is_active"] else "No"
        desc = (row["description"] or "")[:30]
        sub_stage = row.get("sub_stage") or "-"
        print(f"{row['stage']:<15} {sub_stage:<30} {row['version']:<10} {active:<8} {desc:<30}")

    print("-" * 120)


def _add_stages_argument(parser, verb: str):
    parser.add_argument(
        "--stages",
        nargs="+",
        help=f"Specific stages to {verb} (default: all). Use format: stage/sub_stage (e.g., stage_1/initial_detection)",
        choices=[_stage_label(k) for k in PROMPT_MAPPING],
    )


def main():
    parser = argparse.ArgumentParser(description="Import prompts from files to database")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Import command
    import_parser = subparsers.add_parser("import", help="Import prompts to database")
    source = import_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--version", help="Version number (e.g., 1.0.0) applied to every imported entry")
    source.add_argument(
        "--from-manifest",
        action="store_true",
        help="Import and activate every prompts/manifest.json entry whose version differs from the active DB version",
    )
    import_parser.add_argument("--description", default="Imported from files", help="Version description")
    import_parser.add_argument(
        "--no-active",
        action="store_true",
        help="Don't set as active version (ignored with --from-manifest)",
    )
    _add_stages_argument(import_parser, "import")
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing to database",
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List prompt versions")
    list_parser.add_argument("--active", action="store_true", help="Only list active versions")

    # Diff command
    diff_parser = subparsers.add_parser("diff", help="Compare local prompt files with the active database versions")
    _add_stages_argument(diff_parser, "compare")
    diff_parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff for each differing field",
    )

    args = parser.parse_args()

    try:
        if args.command == "import" and args.from_manifest:
            if import_from_manifest(dry_run=args.dry_run):
                sys.exit(1)
        elif args.command == "import":
            stages = [_parse_stage_label(s) for s in args.stages] if args.stages else None
            if import_prompts(
                version=args.version,
                description=args.description,
                set_active=not args.no_active,
                stages=stages,
                dry_run=args.dry_run,
            ):
                sys.exit(1)
        elif args.command == "list":
            list_versions(active_only=args.active)
        elif args.command == "diff":
            stages = [_parse_stage_label(s) for s in args.stages] if args.stages else None
            sys.exit(diff_prompts(stages=stages, show_diff=args.show_diff))
        else:
            parser.print_help()
    except MissingEnvError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(MISSING_ENV_EXIT_CODE)


if __name__ == "__main__":
    main()
