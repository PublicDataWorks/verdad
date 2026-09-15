#!/usr/bin/env python3
"""Fail when a prompt file changed against the base commit without a manifest version bump.

Usage: PYTHONPATH=. python scripts/ci/check_manifest_bump.py <base-sha>
"""

import json
import subprocess
import sys

from src.scripts.prompt_manifest import load_manifest, manifest_files


def unbumped_entries(manifest: dict, base_manifest: dict, changed_files: set[str]) -> list[str]:
    """Labels whose files changed while the version equals the base manifest's."""
    return [
        label
        for label, entry in manifest.items()
        if set(manifest_files(entry).values()) & changed_files
        and base_manifest.get(label, {}).get("version") == entry["version"]
    ]


def main(base: str) -> int:
    changed = set(subprocess.check_output(["git", "diff", "--name-only", base, "HEAD"], text=True).split())
    try:
        base_manifest = json.loads(
            subprocess.check_output(
                ["git", "show", f"{base}:prompts/manifest.json"], text=True, stderr=subprocess.DEVNULL
            )
        )
    except subprocess.CalledProcessError:
        base_manifest = {}  # manifest is new in this change; nothing to compare against
    unbumped = unbumped_entries(load_manifest(), base_manifest, changed)
    for label in unbumped:
        print(f"::error::{label}: prompt files changed but prompts/manifest.json still says version "
              f"{base_manifest[label]['version']}; bump it or the change will never deploy")
    return 1 if unbumped else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
