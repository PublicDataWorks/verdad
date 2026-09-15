"""
Prompt version manifest: the single source of truth for which prompt files make up
each stage/sub_stage entry and which semver version the working tree represents.

The manifest lives at ``prompts/manifest.json`` and is keyed by a display label:
``"stage_3"`` for entries without a sub-stage, ``"stage_1/disinformation_detection"``
otherwise. Each entry is::

    {
      "version": "1.3.0",
      "description": "Why this version exists",
      "files": {"system_instruction": path | null, "user_prompt": path | null, "output_schema": path | null}
    }

This module has no pipeline or database dependencies so that both
``import_prompts_to_db.py`` and ``evaluate_prompt.py`` can import it.
"""

import json
import os
import re
from dataclasses import dataclass

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(REPO_ROOT, "prompts", "manifest.json")
FILE_TYPES = ("system_instruction", "user_prompt", "output_schema")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_version(version: str) -> bool:
    return bool(SEMVER_RE.match(version or ""))


def stage_label(stage: str, sub_stage: str | None) -> str:
    """Format a stage/sub_stage pair as the manifest key."""
    return stage if sub_stage is None else f"{stage}/{sub_stage}"


def split_stage_label(label: str) -> tuple[str, str | None]:
    """Inverse of :func:`stage_label`."""
    stage, _, sub_stage = label.partition("/")
    return stage, (sub_stage or None)


def load_manifest(path: str = MANIFEST_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Manifest must be a non-empty JSON object keyed by stage/sub_stage")
    for label, entry in manifest.items():
        if not validate_version(entry.get("version")):
            raise ValueError(f"{label}: version {entry.get('version')!r} is not semver (x.y.z)")
        files = entry.get("files")
        if not isinstance(files, dict) or not any(files.get(t) for t in FILE_TYPES):
            raise ValueError(f"{label}: 'files' must name at least one of {FILE_TYPES}")
        unknown = set(files) - set(FILE_TYPES)
        if unknown:
            raise ValueError(f"{label}: unknown file types {sorted(unknown)}")


def manifest_files(entry: dict) -> dict:
    """Return the entry's file paths without the null placeholders."""
    return {file_type: path for file_type, path in entry["files"].items() if path}


def resolve_manifest_path(path: str, root: str, within: str | None = None) -> str:
    """
    Join a manifest file path to ``root`` and return the resolved absolute path, refusing anything that
    does not stay inside ``within`` (default ``root``): absolute paths, ``..`` segments and symlinks that
    resolve elsewhere. A manifest from a pull-request checkout is untrusted input.
    """
    if os.path.isabs(path):
        raise ValueError(f"manifest path {path!r} must be relative, not absolute")
    allowed = os.path.realpath(within or root)
    resolved = os.path.realpath(os.path.join(root, path))
    if os.path.commonpath([allowed, resolved]) != allowed:
        raise ValueError(f"manifest path {path!r} resolves outside {allowed}")
    return resolved


def read_prompt_files(entry: dict) -> dict:
    """Load the text/JSON contents named by a manifest entry (schema parsed as JSON)."""
    data = {}
    for file_type, path in manifest_files(entry).items():
        with open(path, "r", encoding="utf-8") as f:
            data[file_type] = json.load(f) if file_type == "output_schema" else f.read()
    return data


@dataclass(frozen=True)
class ManifestAction:
    label: str
    manifest_version: str
    active_version: str | None
    action: str  # "import" | "up-to-date" | "conflict"
    reason: str


def plan_manifest_import(manifest: dict, db_versions: list[dict]) -> list[ManifestAction]:
    """
    Decide, per manifest entry, whether the DB needs a new version.

    ``db_versions`` rows have ``stage``, ``sub_stage``, ``version`` and ``is_active``
    (the full ``prompt_versions`` listing). The result is deterministic and has no
    side effects so it can be unit-tested without a database.

    - ``up-to-date``: the active DB version equals the manifest version.
    - ``import``: the manifest version does not exist in the DB yet; import and activate it.
    - ``conflict``: the manifest version exists in the DB but is not the active one. The
      ``(stage, sub_stage, version)`` unique constraint would reject a re-import, so the
      manifest must be bumped to a fresh version instead.
    """
    known: dict[str, set[str]] = {}
    active: dict[str, str] = {}
    for row in db_versions:
        label = stage_label(row["stage"], row.get("sub_stage"))
        known.setdefault(label, set()).add(row["version"])
        if row.get("is_active"):
            active[label] = row["version"]

    actions = []
    for label, entry in manifest.items():
        wanted = entry["version"]
        current = active.get(label)
        if current == wanted:
            actions.append(ManifestAction(label, wanted, current, "up-to-date", "active version matches manifest"))
        elif wanted in known.get(label, set()):
            actions.append(
                ManifestAction(
                    label,
                    wanted,
                    current,
                    "conflict",
                    f"version {wanted} already exists in the database but is not active; bump the manifest version",
                )
            )
        else:
            reason = "no active version in database" if current is None else f"active version is {current}"
            actions.append(ManifestAction(label, wanted, current, "import", reason))
    return actions


def format_plan(actions: list[ManifestAction]) -> str:
    width = max(len(a.label) for a in actions) if actions else 10
    lines = [f"{'Entry':<{width}}  {'Manifest':<10} {'Active':<10} Action"]
    lines.append("-" * (width + 40))
    for a in actions:
        lines.append(
            f"{a.label:<{width}}  {a.manifest_version:<10} {(a.active_version or '-'):<10} {a.action} ({a.reason})"
        )
    return "\n".join(lines)
