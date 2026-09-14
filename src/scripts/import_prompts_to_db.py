#!/usr/bin/env python3
"""
Script to import prompt files into the database as versioned entries.

Usage:
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --description "Initial import from files"
    python src/scripts/import_prompts_to_db.py import --version 1.1.0 --description "Updated Stage 3 prompt" --no-active
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --dry-run  # Preview changes without committing
    python src/scripts/import_prompts_to_db.py list
    python src/scripts/import_prompts_to_db.py diff  # Compare local files with active DB versions
    python src/scripts/import_prompts_to_db.py diff --stages stage_3 --show-diff
"""

import argparse
import difflib
import json
import os
import re
import sys

from dotenv import load_dotenv
from supabase import create_client

from src.processing_pipeline.constants import PromptStage
from src.processing_pipeline.stage_1.constants import Stage1SubStage
from src.processing_pipeline.stage_4.constants import Stage4SubStage

load_dotenv()

ALLOWED_PROMPT_DIR = "prompts"
MAX_DESCRIPTION_LENGTH = 500
PROMPT_FIELDS = ("system_instruction", "user_prompt", "output_schema")

PROMPT_MAPPING = {
    (PromptStage.STAGE_1, Stage1SubStage.DISINFORMATION_DETECTION): {
        "system_instruction": "prompts/stage_1/main/detection_system_instruction.md",
        "user_prompt": "prompts/stage_1/main/detection_user_prompt.md",
        "output_schema": "prompts/stage_1/main/detection_output_schema.json",
    },
    (PromptStage.STAGE_1, Stage1SubStage.INITIAL_TRANSCRIPTION): {
        "user_prompt": "prompts/stage_1/preprocess/initial_transcription_user_prompt.md",
        "output_schema": "prompts/stage_1/preprocess/initial_transcription_output_schema.json",
    },
    (PromptStage.STAGE_1, Stage1SubStage.INITIAL_DETECTION): {
        "system_instruction": "prompts/stage_1/preprocess/initial_detection_system_instruction.md",
        "user_prompt": "prompts/stage_1/preprocess/initial_detection_user_prompt.md",
        "output_schema": "prompts/stage_1/preprocess/initial_detection_output_schema.json",
    },
    (PromptStage.STAGE_3, None): {
        "system_instruction": "prompts/stage_3/system_instruction.md",
        "user_prompt": "prompts/stage_3/analysis_prompt.md",
        "output_schema": "prompts/stage_3/output_schema.json",
    },
    (PromptStage.STAGE_4, Stage4SubStage.KB_RESEARCHER): {
        "system_instruction": "prompts/stage_4/kb_researcher_instruction.md",
    },
    (PromptStage.STAGE_4, Stage4SubStage.WEB_RESEARCHER): {
        "system_instruction": "prompts/stage_4/web_researcher_instruction.md",
    },
    (PromptStage.STAGE_4, Stage4SubStage.REVIEWER): {
        "system_instruction": "prompts/stage_4/reviewer_instruction.md",
        "output_schema": "prompts/stage_4/output_schema.json",
    },
    (PromptStage.STAGE_4, Stage4SubStage.KB_UPDATER): {
        "system_instruction": "prompts/stage_4/kb_updater_instruction.md",
    },
    (PromptStage.STAGE_1, Stage1SubStage.TIMESTAMPED_TRANSCRIPTION): {
        "system_instruction": "prompts/stage_1/main/timestamped_transcription_system_instruction.md",
        "user_prompt": "prompts/stage_1/main/timestamped_transcription_user_prompt.md",
        "output_schema": "prompts/stage_1/main/timestamped_transcription_output_schema.json",
    },
}


def validate_version(version: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", version))


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
    if sub_stage is None:
        return stage.value
    return f"{stage.value}/{sub_stage.value}"


def _parse_stage_label(label: str):
    """Parse a display string back to a (stage, sub_stage) tuple."""
    for key in PROMPT_MAPPING:
        if _stage_label(key) == label:
            return key
    return None


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


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _create_client():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

    return create_client(supabase_url, supabase_key)


def load_local_prompt(files: dict) -> dict | None:
    """Read the prompt files for one PROMPT_MAPPING entry. Returns None if any file is missing."""
    if not all(os.path.exists(path) for path in files.values()):
        return None
    return {
        file_type: read_json(path) if file_type == "output_schema" else read_file(path)
        for file_type, path in files.items()
    }


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
        for field in PROMPT_FIELDS
        if _normalize_field(field, local.get(field)) != _normalize_field(field, db_row.get(field))
    ]
    return ("differs" if differing else "in sync"), differing


def fetch_active_prompts(client) -> dict:
    """Return the active prompt_versions rows keyed by (stage, sub_stage)."""
    response = (
        client.table("prompt_versions")
        .select("id, stage, sub_stage, version, description, created_at, " + ", ".join(PROMPT_FIELDS))
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


def import_prompts(
    version: str,
    description: str,
    set_active: bool = True,
    stages: list = None,
    dry_run: bool = False,
):
    """
    Import prompt files into the database.

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
    all_valid, missing_files, unsafe_paths = check_files_exist(keys_to_import)

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

    if not all_valid:
        raise ValueError("File validation failed")

    if dry_run:
        print("\n=== DRY RUN MODE - No changes will be made ===\n")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

    client = None if dry_run else create_client(supabase_url, supabase_key)

    success_count = 0
    error_count = 0

    for key in keys_to_import:
        if key not in PROMPT_MAPPING:
            print(f"Warning: Unknown key '{key}', skipping...")
            continue

        stage, sub_stage = key
        label = _stage_label(key)
        files = PROMPT_MAPPING[key]
        print(f"Importing {label} v{version}...")

        data = load_local_prompt(files)  # files were verified by check_files_exist above

        if dry_run:
            print(f"  Would create version {version} for {label}")
            print(f"    - System instruction: {len(data.get('system_instruction', '')) or 'N/A'} chars")
            print(f"    - User prompt: {len(data.get('user_prompt', '')) or 'N/A'} chars")
            print(f"    - Output schema: {'Yes' if data.get('output_schema') else 'No'}")
            if set_active:
                print(f"    - Would deactivate existing active version and set this as active")
            continue

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

            if response.data:
                result = response.data
                print(f"  Created prompt version: {result['id']}")
                if set_active:
                    print(f"  Set as active version for {label}")
                success_count += 1
            else:
                print(f"  Error: No data returned for {label}")
                error_count += 1

        except Exception as e:
            print(f"  Error creating prompt version for {label}: {e}")
            error_count += 1

    if dry_run:
        print(f"\n=== DRY RUN COMPLETE - No changes were made ({len(keys_to_import)} entries previewed) ===")
    else:
        print(f"\nImport complete! Success: {success_count}, Errors: {error_count}")


def list_versions():
    """List all prompt versions in the database."""
    client = _create_client()

    response = (
        client.table("prompt_versions")
        .select("id, stage, sub_stage, version, is_active, description, created_at")
        .order("stage")
        .order("sub_stage")
        .order("created_at", desc=True)
        .execute()
    )

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
    import_parser.add_argument("--version", required=True, help="Version number (e.g., 1.0.0)")
    import_parser.add_argument("--description", default="Imported from files", help="Version description")
    import_parser.add_argument(
        "--no-active",
        action="store_true",
        help="Don't set as active version",
    )
    _add_stages_argument(import_parser, "import")
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing to database",
    )

    # List command
    subparsers.add_parser("list", help="List all prompt versions")

    # Diff command
    diff_parser = subparsers.add_parser("diff", help="Compare local prompt files with the active database versions")
    _add_stages_argument(diff_parser, "compare")
    diff_parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print a unified diff for each differing field",
    )

    args = parser.parse_args()

    if args.command == "import":
        stages = [_parse_stage_label(s) for s in args.stages] if args.stages else None
        import_prompts(
            version=args.version,
            description=args.description,
            set_active=not args.no_active,
            stages=stages,
            dry_run=args.dry_run,
        )
    elif args.command == "list":
        list_versions()
    elif args.command == "diff":
        stages = [_parse_stage_label(s) for s in args.stages] if args.stages else None
        sys.exit(diff_prompts(stages=stages, show_diff=args.show_diff))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
