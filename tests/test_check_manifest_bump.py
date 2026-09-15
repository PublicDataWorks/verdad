import importlib.util
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "ci", "check_manifest_bump.py")
spec = importlib.util.spec_from_file_location("check_manifest_bump", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def entry(version, *paths):
    return {"version": version, "files": {f"f{i}": p for i, p in enumerate(paths)}}


BASE = {"stage_3": entry("1.3.0", "prompts/stage_3/a.md"), "stage_1/x": entry("2.0.0", "prompts/stage_1/x.md")}


def test_changed_file_without_bump_is_reported():
    assert mod.unbumped_entries(BASE, BASE, {"prompts/stage_3/a.md"}) == ["stage_3"]


def test_changed_file_with_bump_passes():
    head = {**BASE, "stage_3": entry("1.4.0", "prompts/stage_3/a.md")}
    assert mod.unbumped_entries(head, BASE, {"prompts/stage_3/a.md"}) == []


def test_unrelated_change_and_new_entry_pass():
    head = {**BASE, "stage_4/new": entry("1.0.0", "prompts/stage_4/new.md")}
    assert mod.unbumped_entries(head, BASE, {"prompts/stage_4/new.md", "README.md"}) == []


def test_repointed_file_without_bump_is_reported():
    # The version and every file's content are unchanged; only the mapping moved to another existing file.
    head = {**BASE, "stage_3": entry("1.3.0", "prompts/stage_3/b.md")}
    assert mod.unbumped_entries(head, BASE, set()) == ["stage_3"]


def test_dropped_file_without_bump_is_reported():
    head = {**BASE, "stage_1/x": {"version": "2.0.0", "files": {"f0": None}}}
    assert mod.unbumped_entries(head, BASE, set()) == ["stage_1/x"]


def test_mapping_change_with_bump_passes():
    head = {**BASE, "stage_3": entry("1.4.0", "prompts/stage_3/b.md")}
    assert mod.unbumped_entries(head, BASE, set()) == []
