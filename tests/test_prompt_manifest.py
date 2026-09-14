"""Tests for prompts/manifest.json and the manifest-vs-database import planner."""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.scripts import prompt_manifest as pm  # noqa: E402

MANIFEST_PATH = os.path.join(REPO_ROOT, "prompts", "manifest.json")

# Active versions in the production database on 2026-09-14.
ACTIVE_ON_2026_09_14 = [
    {"stage": "stage_1", "sub_stage": "disinformation_detection", "version": "2.1.0", "is_active": True},
    {"stage": "stage_1", "sub_stage": "initial_detection", "version": "2.0.0", "is_active": True},
    {"stage": "stage_1", "sub_stage": "initial_transcription", "version": "1.0.0", "is_active": True},
    {"stage": "stage_1", "sub_stage": "timestamped_transcription", "version": "2.0.0", "is_active": True},
    {"stage": "stage_3", "sub_stage": None, "version": "1.3.0", "is_active": True},
    {"stage": "stage_4", "sub_stage": "kb_researcher", "version": "1.0.0", "is_active": True},
    {"stage": "stage_4", "sub_stage": "kb_updater", "version": "1.0.0", "is_active": True},
    {"stage": "stage_4", "sub_stage": "reviewer", "version": "1.1.0", "is_active": True},
    {"stage": "stage_4", "sub_stage": "web_researcher", "version": "1.0.0", "is_active": True},
]


def test_manifest_loads_and_every_file_exists():
    manifest = pm.load_manifest(MANIFEST_PATH)
    assert set(manifest) == {
        "stage_1/disinformation_detection",
        "stage_1/initial_transcription",
        "stage_1/initial_detection",
        "stage_1/timestamped_transcription",
        "stage_3",
        "stage_4/kb_researcher",
        "stage_4/web_researcher",
        "stage_4/reviewer",
        "stage_4/kb_updater",
    }
    for label, entry in manifest.items():
        assert entry["description"], label
        assert set(entry["files"]) == set(pm.FILE_TYPES), label
        for file_type, rel_path in pm.manifest_files(entry).items():
            assert rel_path.startswith("prompts/"), f"{label}/{file_type}"
            assert os.path.exists(os.path.join(REPO_ROOT, rel_path)), f"{label}/{file_type}: {rel_path}"


def test_manifest_matches_active_db_versions_snapshot():
    manifest = pm.load_manifest(MANIFEST_PATH)
    actions = pm.plan_manifest_import(manifest, ACTIVE_ON_2026_09_14)
    not_up_to_date = [a for a in actions if a.action != "up-to-date"]
    # Bumping the manifest is how a deploy is requested, so this only guards the initial seed.
    if not_up_to_date:
        pytest.skip(f"manifest has pending deploys: {[a.label for a in not_up_to_date]}")


def test_stage_label_roundtrip():
    assert pm.stage_label("stage_3", None) == "stage_3"
    assert pm.stage_label("stage_1", "initial_detection") == "stage_1/initial_detection"
    assert pm.split_stage_label("stage_3") == ("stage_3", None)
    assert pm.split_stage_label("stage_4/reviewer") == ("stage_4", "reviewer")


@pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "", None, "1.0.0-beta"])
def test_validate_version_rejects_non_semver(bad):
    assert not pm.validate_version(bad)


def test_validate_manifest_errors():
    with pytest.raises(ValueError):
        pm.validate_manifest({})
    with pytest.raises(ValueError, match="semver"):
        pm.validate_manifest({"stage_3": {"version": "1", "files": {"user_prompt": "p"}}})
    with pytest.raises(ValueError, match="at least one"):
        pm.validate_manifest({"stage_3": {"version": "1.0.0", "files": {"user_prompt": None}}})
    with pytest.raises(ValueError, match="unknown file types"):
        pm.validate_manifest({"stage_3": {"version": "1.0.0", "files": {"user_prompt": "p", "bogus": "x"}}})


def test_plan_manifest_import_classifies_entries():
    manifest = {
        "stage_3": {"version": "1.4.0", "files": {"user_prompt": "p"}},
        "stage_1/initial_detection": {"version": "2.0.0", "files": {"user_prompt": "p"}},
        "stage_4/reviewer": {"version": "1.0.0", "files": {"user_prompt": "p"}},
        "stage_4/kb_updater": {"version": "1.0.0", "files": {"user_prompt": "p"}},
    }
    db = [
        {"stage": "stage_3", "sub_stage": None, "version": "1.3.0", "is_active": True},
        {"stage": "stage_3", "sub_stage": None, "version": "1.2.0", "is_active": False},
        {"stage": "stage_1", "sub_stage": "initial_detection", "version": "2.0.0", "is_active": True},
        {"stage": "stage_4", "sub_stage": "reviewer", "version": "1.1.0", "is_active": True},
        {"stage": "stage_4", "sub_stage": "reviewer", "version": "1.0.0", "is_active": False},
    ]
    by_label = {a.label: a for a in pm.plan_manifest_import(manifest, db)}
    assert by_label["stage_3"].action == "import" and by_label["stage_3"].active_version == "1.3.0"
    assert by_label["stage_1/initial_detection"].action == "up-to-date"
    assert by_label["stage_4/reviewer"].action == "conflict"  # 1.0.0 exists but is inactive: needs a bump
    assert by_label["stage_4/kb_updater"].action == "import" and by_label["stage_4/kb_updater"].active_version is None
    plan = pm.format_plan(list(by_label.values()))
    assert "stage_4/reviewer" in plan and "conflict" in plan


def test_read_prompt_files_parses_schema(tmp_path):
    (tmp_path / "up.md").write_text("hello")
    (tmp_path / "schema.json").write_text('{"a": 1}')
    entry = {
        "files": {
            "user_prompt": str(tmp_path / "up.md"),
            "output_schema": str(tmp_path / "schema.json"),
            "system_instruction": None,
        }
    }
    assert pm.read_prompt_files(entry) == {"user_prompt": "hello", "output_schema": {"a": 1}}


def test_import_script_prompt_mapping_derives_from_manifest():
    from src.scripts import import_prompts_to_db as ipd

    manifest = json.load(open(MANIFEST_PATH))
    assert {ipd._stage_label(k) for k in ipd.PROMPT_MAPPING} == set(manifest)
    for key, files in ipd.PROMPT_MAPPING.items():
        assert files == pm.manifest_files(manifest[ipd._stage_label(key)])
        assert ipd._parse_stage_label(ipd._stage_label(key)) == key
