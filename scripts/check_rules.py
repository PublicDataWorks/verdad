#!/usr/bin/env python3
"""Validate `.claude/rules/*.md`.

Each rule must have YAML frontmatter with a `paths:` list of globs, and every glob must match at least
one git-tracked file. A stale glob means the rule silently stops loading, which is hard to notice.
"""

import re
import subprocess
import sys
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


def expand_braces(pattern: str) -> list[str]:
    """Expand `{a,b}` groups, which Claude Code globs support, into separate patterns."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    prefix, suffix = pattern[: match.start()], pattern[match.end() :]
    return [expanded for option in match.group(1).split(",") for expanded in expand_braces(prefix + option + suffix)]


def glob_to_regexes(glob: str) -> list[re.Pattern[str]]:
    """Translate a Claude Code rules glob into regexes.

    `**/` spans any number of leading directories, including none, and only ever matches at a path
    boundary - so `**/__tests__/**` matches `__tests__/x.py` and `a/__tests__/x.py` but not
    `a/foo__tests__/x.py`. A bare `**` spans anything; `*` and `?` stay inside one path segment.
    fnmatch cannot express this: its `*` always crosses `/`.
    """
    regexes = []
    for pattern in expand_braces(glob):
        source = ""
        i = 0
        while i < len(pattern):
            if pattern.startswith("**/", i):
                source += "(?:.*/)?"
                i += 3
            elif pattern.startswith("**", i):
                source += ".*"
                i += 2
            elif pattern[i] == "*":
                source += "[^/]*"
                i += 1
            elif pattern[i] == "?":
                source += "[^/]"
                i += 1
            else:
                source += re.escape(pattern[i])
                i += 1
        regexes.append(re.compile(f"^{source}$"))
    return regexes


def matches(glob: str, files: list[str]) -> bool:
    patterns = glob_to_regexes(glob)
    return any(pattern.match(f) for pattern in patterns for f in files)


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
