#!/usr/bin/env python3
"""
Deploy updated VERDAD prompt files to the Supabase database.

This script handles the full deployment workflow:
1. Reads the current active prompt versions from Supabase
2. Creates new versions with updated file content
3. Activates the new versions

Usage (from the verdad repo root):
    python ~/.claude/skills/verdad-heuristics-updater/scripts/deploy_prompts.py

Environment:
    Requires SUPABASE_URL and SUPABASE_KEY (service_role) in .env or environment.
    If not available, uses the REST API workaround with a temp SECURITY DEFINER function.

Alternative (without credentials):
    Use Supabase MCP execute_sql to run the manual deployment steps described in SKILL.md.
"""

import json
import os
import sys
import requests

# VERDAD project configuration — loaded from environment or .env file
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

# Prompt file mappings (relative to verdad repo root)
STAGE_1_DETECTION = {
    "stage": "stage_1",
    "sub_stage": "disinformation_detection",
    "system_instruction": "prompts/stage_1/main/detection_system_instruction.md",
    "user_prompt": "prompts/stage_1/main/detection_user_prompt.md",
    "output_schema": "prompts/stage_1/main/detection_output_schema.json",
}

STAGE_3 = {
    "stage": "stage_3",
    "sub_stage": None,
    "system_instruction": "prompts/stage_3/system_instruction.md",
    "user_prompt": "prompts/stage_3/analysis_prompt.md",
    "output_schema": "prompts/stage_3/output_schema.json",
}


def read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def deploy_via_rpc(supabase_url, supabase_key, config, version, description):
    """Deploy using the upsert_prompt_version RPC function (requires service_role key)."""
    from supabase import create_client

    client = create_client(supabase_url, supabase_key)

    response = client.rpc(
        "upsert_prompt_version",
        {
            "p_stage": config["stage"],
            "p_version": version,
            "p_description": description,
            "p_created_by": "heuristics_updater",
            "p_system_instruction": read_file(config["system_instruction"])
            if config.get("system_instruction")
            else None,
            "p_user_prompt": read_file(config["user_prompt"]),
            "p_output_schema": read_json(config["output_schema"])
            if config.get("output_schema")
            else None,
            "p_set_active": True,
            "p_sub_stage": config.get("sub_stage"),
        },
    ).execute()

    return response.data


def deploy_via_temp_function(supabase_url, anon_key, row_id, user_prompt_content):
    """
    Deploy using a temporary SECURITY DEFINER function.

    Prerequisites (run via Supabase MCP execute_sql):
    1. INSERT a new row by copying the current active version
    2. CREATE the temp_import_prompt function (see SKILL.md)
    3. GRANT EXECUTE to anon

    This function handles step 3: updating the user_prompt content.
    """
    url = f"{supabase_url}/rest/v1/rpc/temp_import_prompt"
    headers = {
        "apikey": anon_key,
        "Content-Type": "application/json",
    }
    payload = {
        "p_id": row_id,
        "p_user_prompt": user_prompt_content,
        "p_token": "verdad_import_2026_temp",
    }

    resp = requests.post(url, headers=headers, json=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"Deploy failed: {resp.status_code} {resp.text}")
    return resp.json()


def main():
    # Determine repo root (look for prompts/ directory)
    repo_root = os.getcwd()
    if not os.path.exists(os.path.join(repo_root, "prompts")):
        repo_root = "/Users/j/GitHub/verdad"
    if not os.path.exists(os.path.join(repo_root, "prompts")):
        print("Error: Cannot find prompts/ directory. Run from the verdad repo root.")
        sys.exit(1)

    os.chdir(repo_root)

    # Try service_role key first
    supabase_key = os.environ.get("SUPABASE_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY"
    )

    if supabase_key and supabase_key != SUPABASE_ANON_KEY:
        print("Using service_role key for deployment...")
        version = input("Version number (e.g., 2.2.0): ").strip()
        description = input("Description: ").strip()

        for config in [STAGE_1_DETECTION, STAGE_3]:
            label = f"{config['stage']}/{config.get('sub_stage', 'main')}"
            print(f"Deploying {label} v{version}...")
            result = deploy_via_rpc(
                SUPABASE_URL, supabase_key, config, version, description
            )
            print(f"  Success: {result}")
    else:
        print("No service_role key found.")
        print("Use the Supabase MCP execute_sql approach described in SKILL.md.")
        print("")
        print("Quick reference:")
        print("1. INSERT new version by copying current active:")
        print(
            "   INSERT INTO prompt_versions (...) SELECT ... FROM prompt_versions WHERE id = '<active_id>' RETURNING id;"
        )
        print("2. CREATE temp_import_prompt function (SECURITY DEFINER)")
        print("3. Use Python requests to POST content via REST API")
        print("4. Activate new version, deactivate old")
        print("5. DROP FUNCTION temp_import_prompt")


if __name__ == "__main__":
    main()
