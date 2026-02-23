#!/usr/bin/env python3
"""
Script to import prompt files into the database as versioned entries.

Usage:
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --description "Initial import from files"
    python src/scripts/import_prompts_to_db.py import --version 1.1.0 --description "Updated Stage 3 prompt" --no-active
    python src/scripts/import_prompts_to_db.py import --version 1.0.0 --dry-run  # Preview changes without committing
    python src/scripts/import_prompts_to_db.py list
"""

import argparse
import json
import os
import re

from dotenv import load_dotenv
from supabase import create_client

from src.processing_pipeline.constants import PromptStage

load_dotenv()

ALLOWED_PROMPT_DIR = "prompts"
MAX_DESCRIPTION_LENGTH = 500

PROMPT_MAPPING = {
    PromptStage.STAGE_1: {
        "system_instruction": "prompts/stage_1/main/detection_system_instruction.md",
        "user_prompt": "prompts/stage_1/main/detection_user_prompt.md",
        "output_schema": "prompts/stage_1/main/detection_output_schema.json",
    },
    PromptStage.STAGE_1_INITIAL_TRANSCRIPTION: {
        "user_prompt": "prompts/stage_1/preprocess/initial_transcription_user_prompt.md",
        "output_schema": "prompts/stage_1/preprocess/initial_transcription_output_schema.json",
    },
    PromptStage.STAGE_1_INITIAL_DETECTION: {
        "system_instruction": "prompts/stage_1/preprocess/initial_detection_system_instruction.md",
        "user_prompt": "prompts/stage_1/preprocess/initial_detection_user_prompt.md",
        "output_schema": "prompts/stage_1/preprocess/initial_detection_output_schema.json",
    },
    PromptStage.STAGE_3: {
        "system_instruction": "prompts/stage_3/system_instruction.md",
        "user_prompt": "prompts/stage_3/analysis_prompt.md",
        "output_schema": "prompts/stage_3/output_schema.json",
    },
    PromptStage.STAGE_4_KB_RESEARCHER: {
        "system_instruction": "prompts/stage_4/kb_researcher_instruction.md",
    },
    PromptStage.STAGE_4_WEB_RESEARCHER: {
        "system_instruction": "prompts/stage_4/web_researcher_instruction.md",
    },
    PromptStage.STAGE_4_REVIEWER: {
        "system_instruction": "prompts/stage_4/reviewer_instruction.md",
        "output_schema": "prompts/stage_4/output_schema.json",
    },
    PromptStage.STAGE_4_KB_UPDATER: {
        "system_instruction": "prompts/stage_4/kb_updater_instruction.md",
    },
    PromptStage.GEMINI_TIMESTAMPED_TRANSCRIPTION: {
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


def check_files_exist(stages: list) -> tuple[bool, list[str], list[str]]:
    missing_files = []
    unsafe_paths = []
    for stage in stages:
        if stage not in PROMPT_MAPPING:
            continue
        files = PROMPT_MAPPING[stage]
        for file_type, path in files.items():
            if not validate_path_safety(path):
                unsafe_paths.append(f"{stage}/{file_type}: {path}")
            elif not os.path.exists(path):
                missing_files.append(f"{stage}/{file_type}: {path}")
    return len(missing_files) == 0 and len(unsafe_paths) == 0, missing_files, unsafe_paths


def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    stages_to_import = stages if stages else list(PROMPT_MAPPING.keys())
    all_valid, missing_files, unsafe_paths = check_files_exist(stages_to_import)

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

    for stage in stages_to_import:
        if stage not in PROMPT_MAPPING:
            print(f"Warning: Unknown stage '{stage}', skipping...")
            continue

        files = PROMPT_MAPPING[stage]
        print(f"Importing {stage} v{version}...")

        data = {}

        # Load each component if file exists
        if files.get("system_instruction"):
            try:
                data["system_instruction"] = read_file(files["system_instruction"])
            except FileNotFoundError:
                print(f"  Warning: {files['system_instruction']} not found")

        if files.get("user_prompt"):
            try:
                data["user_prompt"] = read_file(files["user_prompt"])
            except FileNotFoundError:
                print(f"  Warning: {files['user_prompt']} not found")

        if files.get("output_schema"):
            try:
                data["output_schema"] = read_json(files["output_schema"])
            except FileNotFoundError:
                print(f"  Warning: {files['output_schema']} not found")

        if dry_run:
            print(f"  Would create version {version} for {stage}")
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
                    "p_stage": stage,
                    "p_version": version,
                    "p_description": description,
                    "p_created_by": "import_script",
                    "p_system_instruction": data.get("system_instruction"),
                    "p_user_prompt": data.get("user_prompt"),
                    "p_output_schema": data.get("output_schema"),
                    "p_set_active": set_active,
                },
            ).execute()

            if response.data:
                result = response.data
                print(f"  Created prompt version: {result['id']}")
                if set_active:
                    print(f"  Set as active version for {stage}")
                success_count += 1
            else:
                print(f"  Error: No data returned for {stage}")
                error_count += 1

        except Exception as e:
            print(f"  Error creating prompt version for {stage}: {e}")
            error_count += 1

    if dry_run:
        print(f"\n=== DRY RUN COMPLETE - No changes were made ({len(stages_to_import)} stages previewed) ===")
    else:
        print(f"\nImport complete! Success: {success_count}, Errors: {error_count}")


def list_versions():
    """List all prompt versions in the database."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")

    client = create_client(supabase_url, supabase_key)

    response = (
        client.table("prompt_versions")
        .select("id, stage, version, is_active, description, created_at")
        .order("stage")
        .order("created_at", desc=True)
        .execute()
    )

    if not response.data:
        print("No prompt versions found in database.")
        return

    print("\nPrompt Versions:")
    print("-" * 100)
    print(f"{'Stage':<40} {'Version':<10} {'Active':<8} {'Description':<30}")
    print("-" * 100)

    for row in response.data:
        active = "Yes" if row["is_active"] else "No"
        desc = (row["description"] or "")[:30]
        print(f"{row['stage']:<40} {row['version']:<10} {active:<8} {desc:<30}")

    print("-" * 100)


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
    import_parser.add_argument(
        "--stages",
        nargs="+",
        help="Specific stages to import (default: all)",
        choices=list(PROMPT_MAPPING.keys()),
    )
    import_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without committing to database",
    )

    # List command
    subparsers.add_parser("list", help="List all prompt versions")

    args = parser.parse_args()

    if args.command == "import":
        import_prompts(
            version=args.version,
            description=args.description,
            set_active=not args.no_active,
            stages=args.stages,
            dry_run=args.dry_run,
        )
    elif args.command == "list":
        list_versions()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
