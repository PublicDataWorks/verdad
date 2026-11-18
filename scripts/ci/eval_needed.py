#!/usr/bin/env python3
"""Print what a change touches that the Stage 3 prompt evaluation measures, one per line; no output means skip it.

Usage: PYTHONPATH=. python scripts/ci/eval_needed.py <base-rev>
"""

import json
import os
import subprocess
import sys

from src.scripts.prompt_manifest import load_manifest, manifest_files

STAGE_3_LABEL = "stage_3"
MANIFEST = "prompts/manifest.json"
JOB_SCRIPTS = {
    "scripts/ci/fly_prompt_job.sh",
    "scripts/ci/run_prompt_job.sh",
    "scripts/ci/post_pr_comment.py",
    "scripts/ci/upload_eval_artifacts.py",
    "src/scripts/evaluate_prompt.py",
}


def eval_reasons(manifest: dict, base_manifest: dict, changed_files: set[str]) -> list[str]:
    """Changed paths the evaluation job reads or runs: Stage 3 prompt files, eval sets and its own scripts."""
    entry = manifest.get(STAGE_3_LABEL)
    # The manifest changes on every prompt bump; it counts only when the stage_3 entry did.
    reasons = [f"{MANIFEST} ({STAGE_3_LABEL} entry)"] if entry != base_manifest.get(STAGE_3_LABEL) else []
    prompt_files = set(manifest_files(entry).values()) if entry else set()
    for path in sorted(changed_files):
        # run_prompt_job.sh only takes eval sets from the top level of prompts/eval/.
        is_eval_set = os.path.dirname(path) == "prompts/eval" and path.endswith(".json")
        if path in prompt_files or is_eval_set or path in JOB_SCRIPTS:
            reasons.append(path)
    return reasons


def main(base: str) -> None:
    # --no-renames: a moved file must show its old path too.
    diff = subprocess.check_output(["git", "diff", "--name-only", "--no-renames", base, "HEAD"], text=True)
    try:
        base_manifest = json.loads(
            subprocess.check_output(["git", "show", f"{base}:{MANIFEST}"], text=True, stderr=subprocess.DEVNULL)
        )
    except subprocess.CalledProcessError:
        base_manifest = {}  # no manifest at the base
    print("\n".join(eval_reasons(load_manifest(), base_manifest, set(diff.splitlines()))))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
