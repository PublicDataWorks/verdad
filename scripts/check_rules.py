#!/usr/bin/env python3
"""Validate `.claude/rules/*.md`.

Each rule must have YAML frontmatter with a `paths:` list of globs, and every glob must match at least
one git-tracked file. A stale glob means the rule silently stops loading, which is hard to notice.
"""

import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / ".claude" / "rules"


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return out.splitlines()


def parse_paths(rule: Path) -> tuple[list[str], list[str]]:
    """Return (globs, errors) from the rule's frontmatter."""
    lines = rule.read_text().splitlines()
    if not lines or lines[0].strip() != "---":
        return [], [f"{rule.name}: missing YAML frontmatter (first line must be '---')"]
    try:
        end = lines.index("---", 1)
    except ValueError:
        return [], [f"{rule.name}: unterminated frontmatter"]

    globs: list[str] = []
    in_paths = False
    for line in lines[1:end]:
        if line.startswith("paths:"):
            in_paths = True
            continue
        if in_paths and line.lstrip().startswith("- "):
            globs.append(line.lstrip()[2:].strip().strip("\"'"))
        elif line.strip() and not line.startswith((" ", "-")):
            in_paths = False

    if not globs:
        return [], [f"{rule.name}: no 'paths:' globs (the rule would load in every session)"]
    return globs, []


def matches(glob: str, files: list[str]) -> bool:
    # Claude Code globs treat `**` as "any depth"; fnmatch's `*` already crosses `/`,
    # so collapsing `**` to `*` is a conservative check.
    pattern = glob.replace("**", "*")
    return any(fnmatch(f, pattern) for f in files)


def main() -> int:
    if not RULES_DIR.is_dir():
        print(f"No rules directory at {RULES_DIR}")
        return 0

    files = tracked_files()
    errors: list[str] = []
    rules = sorted(RULES_DIR.rglob("*.md"))
    if not rules:
        print(f"No rules found in {RULES_DIR}")
        return 0

    for rule in rules:
        globs, rule_errors = parse_paths(rule)
        errors.extend(rule_errors)
        for glob in globs:
            if not matches(glob, files):
                errors.append(f"{rule.name}: glob '{glob}' matches no tracked file")
        if globs and not rule_errors:
            print(f"ok  {rule.relative_to(REPO_ROOT)}  ({len(globs)} glob(s))")

    for error in errors:
        print(f"ERROR {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
