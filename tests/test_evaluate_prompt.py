"""Unit tests for the Stage 3 prompt evaluation harness (no network, no Gemini)."""

import asyncio
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (REPO_ROOT, os.path.join(REPO_ROOT, "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.scripts import evaluate_prompt as ep  # noqa: E402


def stage3_output(overall=85, categories=("Fabricated Content",), explanation="Because reasons.", statuses=None):
    return {
        "disinformation_categories": [{"spanish": f"{c} (es)", "english": c} for c in categories],
        "explanation": {"english": explanation, "spanish": "..."},
        "confidence_scores": {
            "overall": overall,
            "verification_status": statuses or "verified_false",
            "categories": [{"category": c, "score": overall} for c in categories],
        },
    }


def run(overall=85, categories=("Fabricated Content",), error=None, usage=None, explanation="x"):
    if error:
        return ep.RunResult(error=error)
    r = ep.parse_output(stage3_output(overall, categories, explanation))
    r.usage = usage or {}
    return r


# ---------------------------------------------------------------- parsing / flags


def test_parse_output_extracts_compare_fields():
    result = ep.parse_output(stage3_output(72, ("B", "A"), "Explained"))
    assert result.categories == ["A", "B"]
    assert result.overall == 72
    assert result.category_scores == {"A": 72, "B": 72}
    assert result.verification_status == "verified_false"
    assert result.explanation == "Explained"
    assert result.ok


def test_parse_output_tolerates_missing_fields():
    result = ep.parse_output({})
    assert result.categories == [] and result.overall is None and result.explanation == ""
    assert result.cap_reasons == []


CAP_REASON = "verification_status is 'insufficient_evidence'"


def test_parse_output_reads_cap_reasons_from_grounding_metadata_json():
    grounding = json.dumps({"searches_performed": [], "evidence_gate": {"applied": True, "reasons": [CAP_REASON]}})
    result = ep.parse_output(stage3_output(40), grounding)
    assert result.cap_reasons == [CAP_REASON]


def test_parse_output_reads_cap_reasons_from_inline_gate_or_dict():
    inline = {**stage3_output(40), "evidence_gate": {"applied": True, "reasons": [CAP_REASON, "second"]}}
    assert ep.parse_output(inline).cap_reasons == [CAP_REASON, "second"]
    as_dict = {"evidence_gate": {"applied": True, "reasons": ["r"]}}
    assert ep.parse_output(stage3_output(40), as_dict).cap_reasons == ["r"]


@pytest.mark.parametrize(
    "grounding",
    [None, "", "not json", json.dumps({"searches_performed": []}), json.dumps({"evidence_gate": {"applied": False}})],
)
def test_parse_output_cap_reasons_empty_when_gate_absent_or_unreadable(grounding):
    assert ep.parse_output(stage3_output(85), grounding).cap_reasons == []


def test_is_flagged_uses_threshold_and_flag_on():
    r = ep.parse_output({"confidence_scores": {"overall": 40, "categories": [{"category": "X", "score": 90}]}})
    assert not ep.is_flagged(r, 70, "overall")
    assert ep.is_flagged(r, 70, "category")
    assert ep.is_flagged(r, 40, "overall")
    assert not ep.is_flagged(ep.RunResult(error="boom"), 0)


def test_majority_is_strict():
    assert ep.majority([True, True, False])
    assert not ep.majority([True, False])
    assert not ep.majority([])


# ---------------------------------------------------------------- run summaries


def test_summarize_runs_majority_vote_and_stability():
    runs = [run(90, ("A", "B")), run(80, ("A",)), run(20, ("A",))]
    s = ep.summarize_runs(runs, threshold=70)
    assert s.n_runs == 3 and s.n_ok == 3
    assert s.flagged is True
    assert s.flag_agreement == pytest.approx(2 / 3)
    assert s.mean_confidence == pytest.approx((90 + 80 + 20) / 3)
    assert s.categories == ["A"]  # B appears in only 1 of 3 runs
    assert s.category_stability == pytest.approx((0.5 + 0.5 + 1.0) / 3)
    assert s.explanation == "x"


def test_summarize_runs_ignores_errors_and_handles_all_failed():
    s = ep.summarize_runs([run(error="timeout"), run(95)])
    assert s.n_ok == 1 and s.flagged and s.errors == ["timeout"]
    s = ep.summarize_runs([run(error="a"), run(error="b")])
    assert s.n_ok == 0 and not s.flagged and s.errors == ["a", "b"]


def test_summarize_runs_tie_counts_as_not_flagged():
    s = ep.summarize_runs([run(90), run(10)], threshold=70)
    assert s.flagged is False and s.flag_agreement == 0.5


# ---------------------------------------------------------------- verdicts


def summary(flagged, n_ok=2):
    return ep.RunSummary(n_runs=2, n_ok=n_ok, flagged=flagged)


@pytest.mark.parametrize(
    "kind,base,cand,expected",
    [
        (ep.REPORTED, True, False, ep.FIXED),
        (ep.REPORTED, True, True, ep.UNCHANGED),
        (ep.REPORTED, False, True, ep.NEWLY_FLAGGED),
        (ep.REPORTED, False, False, ep.NOT_FLAGGED_BY_BASELINE),
        (ep.CONTROL, True, False, ep.LOST),
        (ep.CONTROL, True, True, ep.KEPT),
        (ep.CONTROL, False, True, ep.NEWLY_FLAGGED),
        (ep.CONTROL, False, False, ep.NOT_FLAGGED_BY_BASELINE),
    ],
)
def test_snippet_verdict(kind, base, cand, expected):
    assert ep.snippet_verdict(kind, summary(base), summary(cand)) == expected


def test_snippet_verdict_no_data_when_a_side_has_no_successful_runs():
    assert ep.snippet_verdict(ep.REPORTED, summary(True), summary(False, n_ok=0)) == ep.NO_DATA


# ---------------------------------------------------------------- aggregation / cost


def make_result(snippet_id, kind, base_scores, cand_scores, base_cats=("A",), cand_cats=("A",), usage=None):
    r = ep.SnippetResult(snippet_id=snippet_id, kind=kind)
    r.baseline_runs = [run(s, base_cats, usage=usage) for s in base_scores]
    r.candidate_runs = [
        run(s, cand_cats, usage=usage, explanation="Candidate says the claim is true.") for s in cand_scores
    ]
    return r.finalize(threshold=70, flag_on="overall")


def test_aggregate_counts_fixed_and_lost():
    usage = {"prompt_token_count": 1000, "candidates_token_count": 100, "thoughts_token_count": 50}
    results = [
        make_result("r1", ep.REPORTED, [90, 85], [30, 20], cand_cats=(), usage=usage),  # fixed
        make_result("r2", ep.REPORTED, [90, 85], [80, 90], usage=usage),  # unchanged
        make_result("r3", ep.REPORTED, [10, 20], [10, 10], base_cats=(), cand_cats=(), usage=usage),
        make_result("c1", ep.CONTROL, [95, 95], [40, 30], cand_cats=(), usage=usage),  # lost
        make_result("c2", ep.CONTROL, [95, 95], [90, 95], usage=usage),  # kept
    ]
    agg = ep.aggregate(results, "gemini-2.5-pro")
    assert agg["reported_total"] == 3 and agg["control_total"] == 2
    assert agg["false_positives_fixed"] == 1
    assert agg["reported_unchanged"] == 1
    assert agg["reported_not_flagged_by_baseline"] == 1
    assert agg["true_positives_lost"] == 1
    assert agg["control_kept"] == 1
    assert agg["label_churn"] == pytest.approx(2 / 5)  # r1 and c1 dropped their category
    assert agg["mean_confidence_shift"] < 0
    assert agg["runs_total"] == 20 and agg["runs_failed"] == 0
    assert agg["usage"]["prompt_token_count"] == 20_000
    # 20 calls * (1000 input * 1.25 + 150 output * 10.0) / 1M
    assert agg["estimated_cost_usd"] == pytest.approx(20 * (1000 * 1.25 + 150 * 10.0) / 1_000_000)


def test_estimate_cost_unknown_model():
    assert ep.estimate_cost({"prompt_token_count": 10}, "some-future-model") is None


def test_render_report_contains_tables_and_evidence():
    results = [
        make_result("11111111-aaaa", ep.REPORTED, [90, 85], [30, 20], cand_cats=()),
        make_result("22222222-bbbb", ep.CONTROL, [95, 95], [90, 95]),
    ]
    results[0].title = "A | title with pipe"
    agg = ep.aggregate(results, "gemini-2.5-pro")
    config = {
        "baseline": "b",
        "candidate": "c",
        "model": "gemini-2.5-pro",
        "runs": 2,
        "threshold": 70,
        "flag_on": "overall",
    }
    report = ep.render_report(results, agg, config, notes=["one note"])
    assert "| False positives fixed" in report and "1 / 1 |" in report
    assert "| `11111111` | reported | A \\| title with pipe |" in report
    assert "## Evidence" in report and "> Candidate says the claim is true." in report
    assert "`22222222-bbbb`" not in report.split("## Evidence")[1]  # control snippet is not evidence
    assert "- one note" in report


def test_cap_histogram_counts_runs_per_reason_and_arm():
    r = make_result("11111111-aaaa", ep.REPORTED, [90, 85], [30, 20])
    r.baseline_runs[0].cap_reasons = [CAP_REASON]
    r.candidate_runs[0].cap_reasons = [CAP_REASON, "other reason"]
    r.candidate_runs[1].cap_reasons = ["other reason"]
    failed = ep.RunResult(error="boom", cap_reasons=[CAP_REASON])  # failed runs are not counted
    r.candidate_runs.append(failed)

    assert ep.cap_histogram([r]) == [
        {"reason": "other reason", "baseline": 0, "candidate": 2},
        {"reason": CAP_REASON, "baseline": 1, "candidate": 1},
    ]
    assert ep.cap_histogram([make_result("22222222-bbbb", ep.CONTROL, [95], [95])]) == []


def test_render_report_capped_runs_table_and_results_json_carry_cap_reasons():
    results = [make_result("11111111-aaaa", ep.REPORTED, [90, 85], [30, 20])]
    results[0].candidate_runs[0].cap_reasons = ["reason | with pipe"]
    agg = ep.aggregate(results, "gemini-2.5-pro")
    config = {"baseline": "b", "candidate": "c", "model": "m", "runs": 2, "threshold": 70, "flag_on": "overall"}

    report = ep.render_report(results, agg, config)
    assert "## Capped runs by reason" in report
    assert "| reason \\| with pipe | 0 | 1 |" in report

    payload = json.loads(json.dumps(ep.results_to_json(results, agg, config, notes=[])))
    assert payload["snippets"][0]["candidate_runs"][0]["cap_reasons"] == ["reason | with pipe"]
    assert payload["snippets"][0]["baseline_runs"][0]["cap_reasons"] == []

    uncapped = [make_result("22222222-bbbb", ep.CONTROL, [95], [95])]
    assert "## Capped runs by reason" not in ep.render_report(uncapped, ep.aggregate(uncapped, "m"), config)


def test_failure_histogram_groups_by_exception_class():
    r1 = ep.SnippetResult(snippet_id="11111111-aaaa", kind=ep.REPORTED)
    r1.baseline_runs = [run(90), run(error="ServerError: 503 UNAVAILABLE. The model is overloaded")]
    r1.candidate_runs = [run(error="ClientError: 429 RESOURCE_EXHAUSTED"), run(error="ClientError: 429 quota")]
    r2 = ep.SnippetResult(snippet_id="22222222-bbbb", kind=ep.CONTROL)
    r2.baseline_runs = [run(error="ServerError: 500 INTERNAL"), run(90)]
    r2.candidate_runs = [run(90), run(error="no colon here")]
    for r in (r1, r2):
        r.finalize(threshold=70, flag_on="overall")

    hist = ep.failure_histogram([r1, r2])
    assert [(b["kind"], b["count"]) for b in hist] == [("ClientError", 2), ("ServerError", 2), ("no colon here", 1)]
    server = next(b for b in hist if b["kind"] == "ServerError")
    assert server["example"] == "ServerError: 503 UNAVAILABLE. The model is overloaded"
    assert server["snippet_id"] == "11111111-aaaa" and server["side"] == "baseline"
    assert ep.failure_histogram([make_result("ok", ep.REPORTED, [90], [90])]) == []


def test_render_report_failures_section():
    config = {
        "baseline": "b",
        "candidate": "c",
        "model": "gemini-2.5-pro",
        "runs": 2,
        "threshold": 70,
        "flag_on": "overall",
    }
    clean = [make_result("11111111-aaaa", ep.REPORTED, [90, 85], [30, 20], cand_cats=())]
    report = ep.render_report(clean, ep.aggregate(clean, "gemini-2.5-pro"), config)
    assert "## Failures" not in report

    r = ep.SnippetResult(snippet_id="33333333-cccc", kind=ep.REPORTED)
    r.baseline_runs = [run(90), run(error="ServerError: 503 UNAVAILABLE | overloaded")]
    r.candidate_runs = [run(error="ClientError: 429 RESOURCE_EXHAUSTED"), run(error="ClientError: 429 again")]
    r.finalize(threshold=70, flag_on="overall")
    report = ep.render_report([r], ep.aggregate([r], "gemini-2.5-pro"), config, notes=["a note"])
    failures = report.split("## Failures")[1]
    assert "3 of 4 model calls failed" in failures
    assert "| `ClientError` | 2 | `33333333` candidate: ClientError: 429 RESOURCE_EXHAUSTED |" in failures
    assert "| `ServerError` | 1 | `33333333` baseline: ServerError: 503 UNAVAILABLE \\| overloaded |" in failures
    assert failures.index("ClientError") < failures.index("ServerError")  # most frequent first
    assert "## Notes" in failures  # notes still follow the failures section


def test_client_http_options_enables_retries():
    options = ep.client_http_options()
    assert set(options) == {"http_options"}
    retry = options["http_options"].retry_options
    assert retry.attempts == ep.RETRY_ATTEMPTS
    assert retry.initial_delay == ep.RETRY_INITIAL_DELAY and retry.max_delay == ep.RETRY_MAX_DELAY


def test_client_http_options_falls_back_without_sdk_support(monkeypatch, capsys):
    import google.genai.types as types

    monkeypatch.delattr(types, "HttpRetryOptions")
    assert ep.client_http_options() == {}
    assert "retry options unavailable" in capsys.readouterr().out


# ---------------------------------------------------------------- selection helpers


def test_load_snippet_file_accepts_list_and_eval_set(tmp_path):
    plain = tmp_path / "ids.json"
    plain.write_text(json.dumps(["a", "b"]))
    assert ep.load_snippet_file(str(plain)) == (["a", "b"], [], "")

    eval_set = tmp_path / "set.json"
    eval_set.write_text(json.dumps({"description": "d", "reported": ["r"], "control": ["c"]}))
    assert ep.load_snippet_file(str(eval_set)) == (["r"], ["c"], "d")

    bad = tmp_path / "bad.json"
    bad.write_text('"nope"')
    with pytest.raises(ValueError):
        ep.load_snippet_file(str(bad))


def test_pick_control_is_seeded_and_order_independent():
    ids = [f"id-{i}" for i in range(50)]
    a = ep.pick_control(ids, 5, seed=7)
    b = ep.pick_control(list(reversed(ids)), 5, seed=7)
    assert a == b and len(a) == 5 and len(set(a)) == 5
    assert ep.pick_control(ids, 5, seed=8) != a
    assert ep.pick_control(["x"], 5, seed=1) == ["x"]


def test_committed_eval_set_is_well_formed():
    path = os.path.join(REPO_ROOT, "prompts", "eval", "fabricated-content-false-positives-2026-09.json")
    reported, control, description = ep.load_snippet_file(path)
    assert description.startswith("Analyst-reported")
    assert len(reported) == 12 and len(control) == 12
    assert not set(reported) & set(control)
    assert all(len(i) == 36 for i in reported + control)


def test_load_candidate_from_dir_reads_manifest_files(tmp_path):
    prompts = tmp_path / "prompts"
    (prompts / "stage_3").mkdir(parents=True)
    (prompts / "stage_3" / "si.md").write_text("SYS")
    (prompts / "stage_3" / "up.md").write_text("USER")
    (prompts / "stage_3" / "schema.json").write_text('{"type": "object"}')
    (prompts / "manifest.json").write_text(
        json.dumps(
            {
                "stage_3": {
                    "version": "9.9.9",
                    "description": "test",
                    "files": {
                        "system_instruction": "prompts/stage_3/si.md",
                        "user_prompt": "prompts/stage_3/up.md",
                        "output_schema": "prompts/stage_3/schema.json",
                    },
                }
            }
        )
    )
    pv = ep.load_candidate_from_dir(str(prompts))
    assert pv["version"] == "9.9.9"
    assert pv["system_instruction"] == "SYS" and pv["user_prompt"] == "USER"
    assert pv["output_schema"] == {"type": "object"}
    assert pv["id"].startswith("working-tree:")


def test_load_candidate_from_dir_rejects_paths_outside_candidate_dir(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (tmp_path / "secret.md").write_text("SECRET")
    (prompts / "manifest.json").write_text(
        json.dumps({"stage_3": {"version": "9.9.9", "files": {"user_prompt": "../secret.md"}}})
    )
    with pytest.raises(ValueError, match="resolves outside"):
        ep.load_candidate_from_dir(str(prompts))


def test_load_candidate_from_repo_prompts_dir():
    pv = ep.load_candidate_from_dir(os.path.join(REPO_ROOT, "prompts"))
    assert pv["system_instruction"] and pv["user_prompt"] and pv["output_schema"]


# ---------------------------------------------------------------- orchestration with fakes


class FakeDataSource:
    def __init__(self, snippets):
        self.snippets = snippets
        self.downloads = 0

    def fetch_snippet(self, snippet_id):
        return self.snippets.get(snippet_id)

    def download_audio(self, snippet, dest_dir):
        self.downloads += 1
        path = os.path.join(dest_dir, os.path.basename(snippet["file_path"]))
        with open(path, "wb") as f:
            f.write(b"audio")
        return path


class FakeRunner:
    """Baseline prompt flags everything; candidate prompt flags only ids in ``keep``."""

    def __init__(self, keep):
        self.keep = keep
        self.calls = []

    async def run(self, prompt_version, audio_file, metadata):
        self.calls.append((prompt_version["id"], metadata["uuid"], os.path.exists(audio_file)))
        if prompt_version["id"] == "baseline" or metadata["uuid"] in self.keep:
            return run(90, ("Fabricated Content",), usage={"prompt_token_count": 10})
        return run(15, (), usage={"prompt_token_count": 10}, explanation="The claim checks out.")


def fake_snippet(snippet_id):
    return {
        "id": snippet_id,
        "title": {"english": f"Title {snippet_id}", "spanish": "Titulo"},
        "file_path": f"clips/{snippet_id}.mp3",
        "recorded_at": "2026-09-01T12:00:00+00:00",
        "start_time": "00:01:00",
        "end_time": "00:02:00",
        "duration": "00:01:00",
        "audio_file": {
            "radio_station_name": "Test FM",
            "radio_station_code": "TFM",
            "location_state": "TX",
            "location_city": "A",
        },
        "stage_1_llm_response": {
            "detection_result": {
                "flagged_snippets": [
                    {
                        "uuid": snippet_id,
                        "transcription": "hola",
                        "start_time": "00:01:00",
                        "end_time": "00:02:00",
                        "explanation": "e",
                        "keywords_detected": [],
                    }
                ]
            }
        },
    }


def test_evaluate_snippets_end_to_end_with_fakes(capsys):
    data = FakeDataSource(
        {"rep-1": fake_snippet("rep-1"), "ctl-1": fake_snippet("ctl-1"), "ctl-2": fake_snippet("ctl-2")}
    )
    runner = FakeRunner(keep={"ctl-1"})
    selection = [("rep-1", ep.REPORTED), ("missing", ep.REPORTED), ("ctl-1", ep.CONTROL), ("ctl-2", ep.CONTROL)]
    results = asyncio.run(
        ep.evaluate_snippets(
            selection,
            data,
            runner,
            {"id": "baseline"},
            {"id": "candidate"},
            runs=2,
            threshold=70,
            concurrency=2,
        )
    )
    by_id = {r.snippet_id: r for r in results}
    assert by_id["rep-1"].verdict == ep.FIXED and by_id["rep-1"].title == "Title rep-1"
    assert by_id["missing"].verdict == ep.NO_DATA and by_id["missing"].error == "snippet not found"
    assert by_id["ctl-1"].verdict == ep.KEPT
    assert by_id["ctl-2"].verdict == ep.LOST
    assert data.downloads == 3
    assert len(runner.calls) == 12 and all(exists for _, _, exists in runner.calls)
    assert "run failed:" not in capsys.readouterr().out
    # get_metadata was applied: Stage 3 metadata shape reaches the runner unchanged across runs
    assert {uuid for _, uuid, _ in runner.calls} == {"rep-1", "ctl-1", "ctl-2"}

    agg = ep.aggregate(results, "gemini-2.5-pro")
    assert agg["false_positives_fixed"] == 1 and agg["true_positives_lost"] == 1 and agg["no_data"] == 1
    payload = ep.results_to_json(results, agg, {"model": "m"}, [])
    json.dumps(payload)  # serializable


class FailingRunner:
    async def run(self, prompt_version, audio_file, metadata):
        if prompt_version["id"] == "candidate":
            return run(error="ServerError: 503 UNAVAILABLE")
        return run(90)


def test_evaluate_snippets_prints_each_failed_run(capsys):
    data = FakeDataSource({"rep-1": fake_snippet("rep-1")})
    results = asyncio.run(
        ep.evaluate_snippets(
            [("rep-1", ep.REPORTED)], data, FailingRunner(), {"id": "baseline"}, {"id": "candidate"}, runs=2
        )
    )
    out = capsys.readouterr().out
    assert out.count("run failed: rep-1 candidate: ServerError: 503 UNAVAILABLE") == 2
    assert "run failed: rep-1 baseline" not in out
    assert results[0].verdict == ep.NO_DATA and len(results[0].candidate.errors) == 2


def test_main_exits_2_without_environment(monkeypatch, capsys):
    for name in ep.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    assert ep.main(["--snippet-ids", "x"]) == ep.MISSING_ENV_EXIT_CODE
    assert "missing environment variables" in capsys.readouterr().err


def test_fail_on_regression_flag_parsing():
    parser = ep.build_parser()
    assert parser.parse_args([]).fail_on_regression is None
    assert parser.parse_args(["--fail-on-regression"]).fail_on_regression == 0
    assert parser.parse_args(["--fail-on-regression", "2"]).fail_on_regression == 2


def test_exit_code_fails_when_every_call_failed_or_on_regression():
    def agg(total, failed, lost=0):
        return {"runs_total": total, "runs_failed": failed, "true_positives_lost": lost}

    assert ep.exit_code(agg(8, 8), None) == 1
    assert ep.exit_code(agg(8, 7), None) == 0
    assert ep.exit_code(agg(0, 0), None) == 0
    assert ep.exit_code(agg(8, 0, lost=1), None) == 0
    assert ep.exit_code(agg(8, 0, lost=1), 0) == 1
    assert ep.exit_code(agg(8, 0, lost=1), 1) == 0


def test_cap_selection_keeps_both_sets():
    reported, control = ["r1", "r2", "r3"], ["c1", "c2", "c3"]
    assert ep.cap_selection(reported, control, 4) == (["r1", "r2"], ["c1", "c2"])
    assert ep.cap_selection(reported, control, 3) == (["r1", "r2"], ["c1"])
    assert ep.cap_selection(reported, [], 2) == (["r1", "r2"], [])
    assert ep.cap_selection(["r1"], control, 3) == (["r1"], ["c1", "c2"])
    assert ep.cap_selection(reported, control, 10) == (reported, control)


# ---------------------------------------------------------------- error descriptions


def _raise_nested(exc):
    def inner():
        raise exc

    inner()


def test_describe_exception_includes_innermost_frame():
    try:
        _raise_nested(KeyError("search"))
    except KeyError as e:
        text = ep.describe_exception(e)
    assert text.startswith("KeyError: 'search' (at ")
    assert text.endswith(f"tests/test_evaluate_prompt.py:{_raise_nested.__code__.co_firstlineno + 2})")


def test_describe_exception_keeps_location_when_capped():
    try:
        _raise_nested(ValueError("x" * 600))
    except ValueError as e:
        text = ep.describe_exception(e)
    assert len(text) == 500
    assert text.endswith(")") and " (at " in text
    assert ep.failure_histogram([ep.SnippetResult("s", ep.REPORTED, baseline_runs=[ep.RunResult(error=text)])])[0][
        "kind"
    ] == "ValueError"


def test_gemini_runner_reports_error_with_location(monkeypatch):
    async def exploding_run_async(**kwargs):
        _raise_nested(KeyError("search"))

    monkeypatch.setattr(ep.Stage3Executor, "run_async", exploding_run_async)
    result = asyncio.run(ep.GeminiRunner(gemini_client=None, model="m").run({"id": "p"}, "a.mp3", {}))
    assert not result.ok
    assert result.error.startswith("KeyError: 'search' (at ") and "test_evaluate_prompt.py:" in result.error
