import importlib.util
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "ci", "eval_needed.py")
spec = importlib.util.spec_from_file_location("eval_needed", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def entry(version, *paths):
    return {"version": version, "files": {f"f{i}": p for i, p in enumerate(paths)}}


BASE = {"stage_3": entry("1.5.0", "prompts/stage_3/a.md"), "stage_1/x": entry("2.0.0", "prompts/stage_1/x.md")}


def test_other_stage_prompt_with_its_manifest_bump_needs_no_eval():
    head = {**BASE, "stage_1/x": entry("2.1.0", "prompts/stage_1/x.md")}
    assert mod.eval_reasons(head, BASE, {"prompts/stage_1/x.md", "prompts/manifest.json"}) == []


def test_reference_copy_and_stage_4_eval_set_need_no_eval():
    changed = {"prompts/stage_3/heuristics.md", "prompts/eval/stage_4/reviewer.json"}
    assert mod.eval_reasons(BASE, BASE, changed) == []


def test_stage_3_prompt_file_needs_eval():
    head = {**BASE, "stage_3": entry("1.6.0", "prompts/stage_3/a.md")}
    assert mod.eval_reasons(head, BASE, {"prompts/stage_3/a.md", "prompts/manifest.json"}) == [
        "prompts/manifest.json (stage_3 entry)",
        "prompts/stage_3/a.md",
    ]


def test_stage_3_file_edit_without_bump_needs_eval():
    assert mod.eval_reasons(BASE, BASE, {"prompts/stage_3/a.md"}) == ["prompts/stage_3/a.md"]


def test_repointed_stage_3_mapping_needs_eval():
    head = {**BASE, "stage_3": entry("1.5.0", "prompts/stage_3/b.md")}
    assert mod.eval_reasons(head, BASE, {"prompts/manifest.json"}) == ["prompts/manifest.json (stage_3 entry)"]


def test_eval_set_and_the_scripts_the_job_runs_need_eval():
    job = {
        "scripts/ci/fly_prompt_job.sh",
        "scripts/ci/post_pr_comment.py",
        "scripts/ci/run_prompt_job.sh",
        "scripts/ci/upload_eval_artifacts.py",
        "src/scripts/evaluate_prompt.py",
    }
    assert mod.eval_reasons(BASE, BASE, job | {"prompts/eval/set.json", "README.md"}) == [
        "prompts/eval/set.json",
        *sorted(job),
    ]


def test_ci_helpers_outside_the_job_need_no_eval():
    changed = {"scripts/ci/check_manifest_bump.py", "scripts/ci/eval_needed.py"}
    assert mod.eval_reasons(BASE, BASE, changed) == []


def test_job_scripts_list_covers_what_the_job_shell_scripts_call():
    called = set()
    for name in ("fly_prompt_job.sh", "run_prompt_job.sh"):
        with open(os.path.join(REPO_ROOT, "scripts", "ci", name), encoding="utf-8") as f:
            called |= set(re.findall(r"scripts/ci/\w+\.(?:sh|py)", f.read()))
    assert called and called <= mod.JOB_SCRIPTS


def test_new_manifest_needs_eval():
    assert mod.eval_reasons(BASE, {}, {"prompts/manifest.json"}) == ["prompts/manifest.json (stage_3 entry)"]
