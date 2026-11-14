"""Evaluation, cache, runner, report and CLI for the VER-475 pre-check harness (fake provider, no network)."""

import asyncio
import json

import httpx
import pytest

from src.scripts.precheck_eval import cli
from src.scripts.precheck_eval import evaluate as ev
from src.scripts.precheck_eval.cache import ResponseCache, body_hash, cache_key
from src.scripts.precheck_eval.config import Price
from src.scripts.precheck_eval.dataset import load_dataset, parse_clip
from src.scripts.precheck_eval.providers import RateLimitStop, make_client
from src.scripts.precheck_eval.report import build_report, recall_cell, render_markdown
from src.scripts.precheck_eval.runner import dry_run_text, pending, prepare, run_calls, run_variant
from src.scripts.precheck_eval.synthetic import write_dataset
from src.scripts.precheck_eval.variants import questions_for

QUESTIONS = questions_for("standard")


def quiet(*_args, **_kwargs):
    return None


@pytest.fixture
def synth(tmp_path):
    path = tmp_path / "synth.jsonl"
    write_dataset(str(path), n=120, seed=11)
    return str(path)


def make_clip(i, score, split="dev", weight=1.0, **meta):
    return parse_clip(
        {
            "snippet_id": f"c{i}",
            "split": split,
            "weight": weight,
            "stratum": meta.pop("stratum", "s"),
            "label": {"stage3_overall": score, "final_overall": score, "analyzed_by": meta.pop("model", "gemini-3.5-flash")},
            "meta": {"station_code": meta.pop("station", "K1"), "live": meta.pop("live", False), **meta},
            "input": {"stage1_categories": ["A"], "stage1_keywords": ["k"], "stage1_transcript_excerpt": "x" * i},
        }
    )


# ---------------------------------------------------------------- cache


def test_cache_last_record_wins_and_skips_cut_lines(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    assert cache.all_records() == [] and cache.load("fake", "m", "v") == {}
    record = {"key": "k1", "provider": "fake", "model": "fake/signal", "variant": "full.standard", "result": {"error": "x"}}
    cache.append(dict(record))
    cache.append(dict(record, result={"error": None}))
    path = cache.path_for("fake", "fake/signal", "full.standard")
    assert "fake_signal" in str(path)
    with open(path, "a") as f:
        f.write('{"key": "k2", "trunc\n\n')
    assert cache.load("fake", "fake/signal", "full.standard")["k1"]["result"] == {"error": None}
    assert len(cache.all_records()) == 1
    assert body_hash({"a": 1}) == body_hash({"a": 1}) != body_hash({"a": 2})
    assert cache_key("p", "m", "v", "s", "h") != cache_key("p", "m", "v", "s2", "h")


# ---------------------------------------------------------------- runner


def run_fake(clips, cache, *, model="fake-signal", repeats=1, max_calls=None, client=None, retry_errors=False):
    client = client or make_client("fake", model)
    prepared = prepare(clips, client, "full", "standard", QUESTIONS, repeats=repeats)
    return asyncio.run(
        run_calls(client, prepared, cache, "full", "standard", QUESTIONS, max_calls=max_calls,
                  retry_errors=retry_errors, log=quiet)
    )


def test_run_calls_caches_resumes_and_respects_budget(synth, tmp_path):
    clips, _ = load_dataset(synth)
    cache = ResponseCache(tmp_path / "c")
    first = run_fake(clips[:10], cache, max_calls=4)
    assert first["calls"] == 4 and first["not_called_budget"] == 6
    second = run_fake(clips[:10], cache)
    assert second["cached"] == 4 and second["calls"] == 6
    third = run_fake(clips[:10], cache)
    assert third["calls"] == 0 and third["cached"] == 10
    records = cache.all_records()
    assert len(records) == 10 and all("est_request_tokens" in r["state_meta"] for r in records)


def test_repeats_get_their_own_keys_and_reuse_repeat_zero(synth, tmp_path):
    clips, _ = load_dataset(synth)
    cache = ResponseCache(tmp_path / "c")
    run_fake(clips[:3], cache)
    summary = run_fake(clips[:3], cache, repeats=3)
    assert summary["cached"] == 3 and summary["calls"] == 6
    assert sorted({r["repeat"] for r in cache.all_records()}) == [0, 1, 2]


def test_retry_errors_and_rate_limited_records_are_pending(tmp_path):
    clips = [make_clip(i, 10) for i in range(3)]
    client = make_client("fake")
    prepared = prepare(clips, client, "full", "standard", QUESTIONS)
    cached = {
        prepared[0].key: {"result": {"error": "HTTP 500"}},
        prepared[1].key: {"result": {"error": None}, "rate_limited": True},
        prepared[2].key: {"result": {"error": None}},
    }
    assert [p.key for p in pending(prepared, cached)] == [prepared[1].key]
    assert len(pending(prepared, cached, retry_errors=True)) == 2


class StopAfter:
    """A client stand-in that answers once, then reports a rate limit."""

    def __init__(self):
        self.inner = make_client("fake")
        self.spec = self.inner.spec
        self.model = self.inner.model
        self.calls = 0

    def build_body(self, state, questions):
        return self.inner.build_body(state, questions)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def decide(self, state, questions):
        self.calls += 1
        if self.calls > 1:
            raise RateLimitStop("Rate limit exceeded")
        return await self.inner.decide(state, questions)


def test_rate_limit_stops_the_run_cleanly(tmp_path):
    clips = [make_clip(i, 10) for i in range(5)]
    cache = ResponseCache(tmp_path / "c")
    client = StopAfter()
    prepared = prepare(clips, client, "full", "standard", QUESTIONS)
    logs = []
    summary = asyncio.run(run_calls(client, prepared, cache, "full", "standard", QUESTIONS, concurrency=1,
                                    log=logs.append))
    assert summary["rate_limited"] == "Rate limit exceeded" and client.calls == 2
    assert any("Stopped" in line for line in logs)
    records = cache.all_records()
    assert sum(1 for r in records if r["rate_limited"]) == 1
    # Rate-limited records are not results.
    assert len(ev.group_runs(records, {c.snippet_id for c in clips})["fake/fake-signal/full.standard"]) == 1


def test_dry_run_text_and_variant_label():
    clips = [make_clip(i, 10) for i in range(2)]
    client = make_client("parallel", env={"PARALLEL_API_KEY": "secret"})
    prepared = prepare(clips, client, "claim", "neutral", questions_for("neutral"))
    text = dry_run_text(client, prepared, prepared)
    assert "POST https://api.parallel.ai/v1/decisions" in text and "<redacted>" in text and "secret" not in text
    assert "$0.0020" in text and "Provider notes" in text
    unknown = dry_run_text(make_client("typesafe", "jev-1.14", env={}), [], prepared)
    assert "calls to make: 2" in unknown
    assert run_variant("full", "standard") == "full.standard"
    assert run_variant("full", "standard", 1500) == "full.standard.t1500"


# ---------------------------------------------------------------- evaluate


def test_evaluate_fixed_scorer_perfect_ranking():
    clips = [make_clip(i, s, split) for i, (s, split) in enumerate(
        [(0, "dev"), (10, "dev"), (85, "dev"), (95, "dev"), (0, "test"), (20, "test"), (88, "test"), (99, "test")])]
    scorer = ev.Scorer(name="oracle", kind="fixed", values={c.snippet_id: c.score() / 100 for c in clips})
    out = ev.evaluate_scorer(scorer, clips, ev.EvalOptions(bootstrap=50))
    d2t = out["directions"]["dev->test"]
    assert d2t["threshold"] == 0.85
    assert d2t["main"]["skip_rate"]["value"] == 0.5 and d2t["main"]["recall_90"]["value"] == 1.0
    assert out["passes_bar"] is True and out["auroc_80_vs_lt40"] == 1.0
    assert out["pooled"]["main"]["n"]["value"] == 8
    assert set(out["breakdowns"]) == {"stratum", "cohort", "analyzed_by", "stage3_language", "live", "station"}
    assert out["breakdowns"]["cohort"]["3.5-flash backlog"]["n"] == 8


def test_evaluate_random_scorer_and_missing_values_skip_nothing():
    clips = [make_clip(i, 95 if i % 5 == 0 else 5, "dev" if i % 2 else "test") for i in range(40)]
    scorer = ev.Scorer(name="none", kind="fixed", values={})
    out = ev.evaluate_scorer(scorer, clips, ev.EvalOptions(bootstrap=20))
    assert out["n_missing"] == 40
    assert out["pooled"]["main"]["skip_rate"]["value"] == 0.0


def test_evaluate_with_only_one_split():
    clips = [make_clip(i, 10 * i, "dev") for i in range(6)]
    out = ev.evaluate_scorer(ev.always_run_scorer(clips), clips, ev.EvalOptions(bootstrap=10))
    assert out["directions"]["dev->test"]["main"] is None and out["passes_bar"] is None


def test_fitted_scorer_uses_out_of_fold_scores():
    clips = [make_clip(i, 90 if i % 3 == 0 else 5, "dev" if i % 2 else "test") for i in range(60)]

    def featurizer(_train):
        return lambda c: {0: 1.0 if c.score() >= 80 else 0.0}

    scorer = ev.Scorer(name="leaky_on_purpose", kind="fitted", featurizer=featurizer, standardize=True)
    out = ev.evaluate_scorer(scorer, clips, ev.EvalOptions(bootstrap=10))
    assert out["auroc_80_vs_rest"] == 1.0
    assert out["directions"]["dev->test"]["main"]["skip_rate"]["value"] > 0.5


def test_cohort_labels():
    assert ev.cohort(make_clip(1, 0, model="gemini-3.8-flash", live=True)) == "3.8-flash live"
    assert ev.cohort(make_clip(1, 0, live=None)) == "3.5-flash unknown"


def record(sid, answers, repeat=0, created="2026-11-10T00:00:00", error=None, usage=None, state_meta=None, **extra):
    raw = {"answers": answers, "usage": usage or {"input_tokens": 1000}}
    return {
        "key": f"{sid}-{repeat}-{created}",
        "provider": "fake",
        "model": "fake-signal",
        "variant": "full.standard",
        "snippet_id": sid,
        "repeat": repeat,
        "created_at": created,
        "questions_hash": "h",
        "state_meta": state_meta or {"est_request_tokens": 1100, "truncated": False},
        "request": {"state": "s", "questions": QUESTIONS},
        "result": {"error": error, "http_status": 500 if error else 200, "raw": None if error else raw,
                   "usage": raw["usage"], "latency_s": 0.2, "citations": []},
        **extra,
    }


def noul_answers(p):
    return {
        "worth_analysis": {"type": "noul", "noul": p},
        "checkable_claim": {"type": "noul", "noul": p},
        "harm_topic": {"type": "refusal"},
        "stage3_band": {"type": "score", "score": 4 * p},
        "content_type": {"type": "choice", "choice": "religious", "probabilities": {"religious": 1 - p, "news_report": p}},
    }


def test_group_runs_merge_spread_and_cost():
    recs = [
        record("a", noul_answers(0.2), 0),
        record("a", noul_answers(0.6), 1),
        record("a", noul_answers(0.9), 1, created="2026-11-10T00:00:01"),  # later wins for repeat 1
        record("b", {}, 0, error="HTTP 500: boom"),
        record("c", noul_answers(0.5), 0, usage={"input_tokens": 100, "cost": 0.001}),
        record("z", noul_answers(0.5), 0),  # not in the dataset
    ]
    runs = ev.group_runs(recs, {"a", "b", "c"})
    run = runs["fake/fake-signal/full.standard"]
    assert [len(run[s]) for s in ("a", "b", "c")] == [2, 1, 1]
    merged = ev.merge_answers([ev.record_answers(r) for r in run["a"]])
    assert merged["worth_analysis"]["value"] == pytest.approx(0.55)
    assert merged["harm_topic"]["refused"]
    assert merged["content_type"]["choice"] == "news_report"
    assert ev.merge_answers([{}, {}]) == {}
    spread = ev.repeat_spread(run)
    assert spread["worth_analysis"]["max"] == pytest.approx(0.7)
    cost = ev.run_cost(run, Price(input_per_m=1.0))
    assert cost["n_calls"] == 4 and cost["errors"] == 1 and cost["repeats_per_clip"] == pytest.approx(4 / 3)
    assert cost["refusals"] == 3 and cost["suspected_vendor_truncation"] == 1
    assert cost["cost_per_clip"] == pytest.approx((0.001 + 0.001 + 0.001) / 3)
    assert ev.run_cost(run, Price(input_per_m=None))["cost_per_clip"] is None
    scorers = ev.run_scorers(run)
    assert [s.name for s in scorers][-1] == "stacked" and scorers[0].values["b"] is None


def test_record_answers_handles_errors_and_mcp_envelopes():
    assert ev.record_answers(record("a", {}, error="HTTP 500")) == {}
    envelope = record("a", {})
    envelope["result"]["raw"] = {"jsonrpc": "2.0", "result": {"structuredContent": {"answers": noul_answers(0.4)}}}
    assert ev.record_answers(envelope)["worth_analysis"]["value"] == 0.4
    bad = record("a", {})
    bad["result"]["raw"] = {"nope": 1}
    assert ev.record_answers(bad) == {}


def test_savings():
    out = ev.savings(0.5, 0.001, {"a": 0.09, "b": 0.18}, 400)
    assert out["a"] == pytest.approx(400 * (0.045 - 0.001)) and out["b"] == pytest.approx(400 * (0.09 - 0.001))
    assert ev.savings(None, 0.0, {"a": 0.09}, 400) == {"a": None}


def test_baseline_features():
    c = make_clip(10, 50, recorded_at="2026-11-01T13:00:00Z")
    raw = ev.stage1_raw_features(c)
    assert "hour=13" in raw["tags"] and "cat=A" in raw["tags"] and "lang=unknown" in raw["tags"]
    assert ev._hour("not a date") == "unknown" and ev._hour(None) == "unknown"
    featurize = ev.stage1_featurizer([c])
    x = featurize(make_clip(3, 0, station="NEW"))
    assert len(x) == ev.N_NUMERIC_STAGE1 + len(raw["tags"]) and x[0] == 1.0
    odd = parse_clip({"snippet_id": "o", "split": "dev", "input": {"duration_s": "x", "stage1_extra": []}})
    assert ev.stage1_raw_features(odd)["numeric"][4] == 0.0
    t = ev.text_features("Hola hola mundo")
    assert len(t) == 4 and abs(sum(v * v for v in t.values()) - 1.0) < 1e-9
    assert ev.text_features("") == {}
    names = [s.name for s in ev.baseline_scorers([c])]
    assert names == ["always_run", "stage1_fields", "text_lr"]


# ---------------------------------------------------------------- report and CLI


def test_report_end_to_end_with_fake_provider(synth, tmp_path):
    cache_dir = str(tmp_path / "cache")
    for model in ("fake-signal", "fake-random"):
        assert cli.main(["--cache-dir", cache_dir, "run", "--provider", "fake", "--model", model, "--dataset", synth],
                        log=quiet) == 0
    assert cli.main(["--cache-dir", cache_dir, "run", "--provider", "fake", "--variant", "claim", "--repeats", "2",
                     "--dataset", synth, "--limit", "30"], log=quiet) == 0
    out, js = tmp_path / "r.md", tmp_path / "r.json"
    assert cli.main(["--cache-dir", cache_dir, "report", "--dataset", synth, "--bootstrap", "50", "--out", str(out),
                     "--json", str(js), "--text-epochs", "3", "--stage3-cost", "x=0.1"], log=quiet) == 0
    report = json.loads(js.read_text())
    runs = {r["id"]: r for r in report["runs"]}
    signal = {s["name"]: s for s in runs["fake/fake-signal/full.standard"]["scorers"]}
    noise = {s["name"]: s for s in runs["fake/fake-random/full.standard"]["scorers"]}
    # A scorer that follows the input signal ranks well and skips a lot; noise does not.
    assert signal["worth_analysis"]["auroc_80_vs_lt40"] > 0.85
    assert noise["worth_analysis"]["auroc_80_vs_lt40"] < 0.75
    assert signal["worth_analysis"]["pooled"]["main"]["skip_rate"]["value"] > 0.4
    assert runs["fake/fake-signal/claim.standard"]["repeat_spread"]
    assert report["config"]["stage3_costs"] == {"x": 0.1}
    markdown = out.read_text()
    assert "## Pick on dev, measure on test" in markdown and "always_run" in markdown and "\u2014" not in markdown
    assert "Spread across repeated calls" in markdown and "LB" in markdown


def test_report_filters_and_common_clips(synth, tmp_path):
    clips, _ = load_dataset(synth)
    cache = ResponseCache(tmp_path / "c")
    run_fake(clips[:40], cache)
    run_fake(clips[20:60], cache, model="fake-random")
    report = build_report(clips, cache.all_records(), ev.EvalOptions(bootstrap=10), common_clips=True,
                          with_baselines=False, problems=["dataset: line 3: bad"])
    assert all(r["n_clips"] == 20 for r in report["runs"])
    assert any("--common-clips" in n for n in report["notes"])
    only = build_report(clips, cache.all_records(), ev.EvalOptions(bootstrap=10), with_baselines=False,
                        run_filter=["fake/fake-random/full.standard"])
    assert [r["id"] for r in only["runs"]] == ["fake/fake-random/full.standard"]
    text = render_markdown(report)
    assert "Notes:" in text and "line 3" in text


def test_report_notes_mixed_question_versions_and_web_runs():
    clips = [make_clip(i, 90 if i % 4 == 0 else 0, "dev" if i % 2 else "test") for i in range(12)]
    recs = [record(f"c{i}", noul_answers(0.3), questions_hash=f"h{i % 2}") for i in range(12)]
    for r in recs[:6]:
        r["provider"], r["model"] = "parallel", "fast"
    report = build_report(clips, recs, ev.EvalOptions(bootstrap=5), with_baselines=False)
    assert any("question versions" in n for n in report["notes"])
    web = [r for r in report["runs"] if r["web_grounded"]]
    assert web and web[0]["provider"] == "parallel"
    assert "(web)" in render_markdown(report)


def test_dataset_summary_counts_stage4_changes():
    clips = [make_clip(1, 95), make_clip(2, 92), make_clip(3, 50)]
    clips[0].label["final_overall"] = 40
    clips[1].label["final_overall"] = 91
    report = build_report(clips, [], ev.EvalOptions(bootstrap=0), with_baselines=False)
    assert report["dataset"]["n_90_plus_lowered_by_stage4"] == 2
    assert report["dataset"]["n_90_plus_lowered_below_90_by_stage4"] == 1


def test_recall_cell_formats():
    assert recall_cell(None, 90) == "n/a"
    point = {"recall_90": 1.0, "n_90": 24, "recall_90_lb95": 0.8827}
    assert recall_cell(point, 90) == "100.0% [n=24, LB 88.3%]"
    ci = {"recall_80": {"value": 0.9, "lo": 0.8, "hi": 1.0}, "n_80": {"value": 10}, "recall_80_lb95": {"value": 0.6}}
    assert recall_cell(ci, 80) == "90.0% (80.0% to 100.0%) [n=10, LB 60.0%]"


@pytest.mark.parametrize(
    "provider,model,needle",
    [
        ("typesafe", None, '"model": "jev-latest"'),
        ("cloudflare", "clef-flash", "@cf/cloudflare/clef-flash"),
        ("parallel", None, '"mode": "fast"'),
        ("parallel_mcp", None, "mcp.parallel.ai"),
        ("openrouter", "cloudflare/clef", '"model": "cloudflare/clef"'),
        ("jev_compatible", None, "/v1/systemone"),
    ],
)
def test_dry_run_prints_a_request_for_every_provider(synth, tmp_path, provider, model, needle):
    lines = []
    argv = ["--cache-dir", str(tmp_path / "c"), "run", "--provider", provider, "--dataset", synth, "--dry-run",
            "--limit", "3", "--max-calls", "2"]
    if model:
        argv += ["--model", model]
    assert cli.main(argv, env={}, log=lines.append) == 0
    text = "\n".join(lines)
    assert needle in text and "calls to make: 3" in text and "would stop the run after 2 calls" in text
    body = text[text.index("{", text.index("Body for")):text.index("\nCalls selected")]
    assert "questions" in json.loads(body)


def test_cli_errors(synth, tmp_path):
    logs = []
    base = ["--cache-dir", str(tmp_path / "c"), "run", "--dataset", synth]
    assert cli.main(base + ["--provider", "typesafe"], env={}, log=logs.append) == cli.MISSING_ENV_EXIT_CODE
    assert cli.main(base + ["--provider", "typesafe", "--model", "x"], env={}, log=logs.append) == 1
    assert cli.main(base + ["--provider", "fake", "--split", "dev", "--limit", "0"], log=logs.append) == 1
    assert cli.main(base + ["--provider", "parallel", "--variant", "full", "--dry-run", "--limit", "1"], env={},
                    log=logs.append) == 0
    assert any("VER-443" in line for line in logs)
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--provider", "fake", "--dataset", synth, "--limit", "-1"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["report", "--dataset", synth, "--stage3-cost", "nodollars"])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--provider", "fake", "--dataset", synth, "--limit", "x"])
    assert cli.stage3_cost("a=0.5") == ("a", 0.5)


def test_cli_run_against_mock_http_and_all_fail_exit(synth, tmp_path):
    def handler(request):
        return httpx.Response(401, json={"detail": {"message": "Must supply an API key!"}})

    logs = []
    argv = ["--cache-dir", str(tmp_path / "c"), "run", "--provider", "typesafe", "--dataset", synth, "--limit", "2",
            "--ids-file", str(tmp_path / "ids.txt")]
    (tmp_path / "ids.txt").write_text("synthetic-00000\nsynthetic-00001\n")
    assert cli.main(argv, env={"TYPESAFE_API_KEY": "k"}, transport=httpx.MockTransport(handler), log=logs.append) == 1
    assert any("Must supply an API key" in line for line in logs)


def test_cli_rate_limited_exit_code(synth, tmp_path, monkeypatch):
    async def limited(self, state, questions):
        raise RateLimitStop("rate limited")

    monkeypatch.setattr("src.scripts.precheck_eval.providers.McpDecisionClient.decide", limited)
    monkeypatch.setattr("src.scripts.precheck_eval.providers.McpDecisionClient.__aenter__",
                        lambda self: asyncio.sleep(0, result=self))
    argv = ["--cache-dir", str(tmp_path / "c"), "run", "--provider", "parallel_mcp", "--dataset", synth, "--limit", "3"]
    assert cli.main(argv, env={}, log=quiet) == cli.RATE_LIMITED_EXIT_CODE


def test_cli_synth_and_default_report_paths(tmp_path):
    out = tmp_path / "s.jsonl"
    assert cli.main(["synth", "--out", str(out), "--n", "30"], log=quiet) == 0
    cache_dir = tmp_path / "root" / "cache"
    assert cli.main(["--cache-dir", str(cache_dir), "report", "--dataset", str(out), "--no-baselines",
                     "--bootstrap", "0"], log=quiet) == 0
    assert (tmp_path / "root" / "report.md").exists() and (tmp_path / "root" / "report.json").exists()
