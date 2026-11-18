"""Score every cached run against the dataset and render Markdown + JSON. No network."""

from datetime import datetime, timezone

from .config import (
    CLIPS_PER_DAY,
    PROVIDERS,
    SCORE_BANDS,
    SKIP_RATE_GRID,
    STAGE3_COST_PER_CLIP,
    TRUNCATION_SUSPECT_RATIO,
    Price,
    is_web_grounded,
    price_for,
)
from .dataset import Clip
from .evaluate import (
    TEXT_EPOCHS,
    EvalOptions,
    baseline_scorers,
    evaluate_scorer,
    group_runs,
    repeat_spread,
    run_cost,
    run_scorers,
    savings,
)
from .metrics import band_name


def build_report(
    clips: list[Clip],
    records: list[dict],
    opts: EvalOptions | None = None,
    stage3_costs: dict | None = None,
    clips_per_day: float = CLIPS_PER_DAY,
    run_filter: list[str] | None = None,
    common_clips: bool = False,
    with_baselines: bool = True,
    text_epochs: int = TEXT_EPOCHS,
    problems: list[str] | None = None,
) -> dict:
    opts = opts or EvalOptions()
    stage3_costs = dict(stage3_costs or STAGE3_COST_PER_CLIP)
    labeled = [c for c in clips if c.score(opts.label_field) is not None]
    runs = group_runs(records, {c.snippet_id for c in labeled})
    if run_filter:
        runs = {k: v for k, v in runs.items() if k in run_filter}
    notes = list(problems or [])
    baseline_clips = labeled
    if common_clips and runs:
        shared = set.intersection(*(set(v) for v in runs.values()))
        baseline_clips = [c for c in labeled if c.snippet_id in shared]
        runs = {k: {sid: r for sid, r in v.items() if sid in shared} for k, v in runs.items()}
        notes.append(f"--common-clips: every run and baseline is scored on the {len(shared)} clips all runs share.")

    report = {
        "config": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "label_field": opts.label_field,
            "bootstrap": opts.bootstrap,
            "seed": opts.seed,
            "bar": {"recall_90": opts.min_recall_90, "recall_80": opts.min_recall_80},
            "strict_recall_80": opts.strict_recall_80,
            "stage3_costs": stage3_costs,
            "clips_per_day": clips_per_day,
        },
        "dataset": dataset_summary(clips, labeled, opts.label_field),
        "notes": notes,
        "runs": [],
        "baselines": [],
    }
    for rid in sorted(runs):
        records_by_clip = runs[rid]
        provider, model = rid.split("/")[0], "/".join(rid.split("/")[1:-1])
        run_clips = [c for c in labeled if c.snippet_id in records_by_clip]
        price = price_for(provider, model) if provider in PROVIDERS else Price(input_per_m=None)
        cost = run_cost(records_by_clip, price)
        hashes = sorted({r.get("questions_hash") for recs in records_by_clip.values() for r in recs
                         if r.get("questions_hash")})
        if len(hashes) > 1:
            report["notes"].append(f"{rid}: records carry {len(hashes)} question versions; latest per clip is used.")
        scorers = [evaluate_scorer(s, run_clips, opts) for s in run_scorers(records_by_clip)]
        for s in scorers:
            s["savings_per_day"] = savings(_pooled_skip(s), cost["cost_per_clip"], stage3_costs, clips_per_day)
        report["runs"].append(
            {
                "id": rid,
                "provider": provider,
                "model": model,
                "web_grounded": is_web_grounded(provider, model),
                "n_clips": len(run_clips),
                "questions_hashes": hashes,
                "cost": cost,
                "repeat_spread": repeat_spread(records_by_clip),
                "scorers": scorers,
            }
        )
    if with_baselines:
        for scorer in baseline_scorers(baseline_clips, text_epochs=text_epochs):
            result = evaluate_scorer(scorer, baseline_clips, opts)
            result["savings_per_day"] = savings(_pooled_skip(result), 0.0, stage3_costs, clips_per_day)
            report["baselines"].append(result)
    return report


def _pooled_skip(result: dict):
    pooled = (result.get("pooled") or {}).get("main")
    return pooled["skip_rate"]["value"] if pooled else None


def dataset_summary(clips: list[Clip], labeled: list[Clip], label_field: str) -> dict:
    total_w = sum(c.weight for c in labeled)

    def share(pred):
        return sum(c.weight for c in labeled if pred(c.score(label_field))) / total_w if total_w else None

    def lowered_by_stage4(c: Clip) -> bool:
        final = c.score("final_overall")
        return c.score(label_field) >= 90 and final is not None and final < c.score(label_field)

    return {
        "n_clips": len(clips),
        "n_labeled": len(labeled),
        "n_dev": sum(1 for c in labeled if c.split == "dev"),
        "n_test": sum(1 for c in labeled if c.split == "test"),
        "n_80_plus": sum(1 for c in labeled if c.score(label_field) >= 80),
        "n_90_plus": sum(1 for c in labeled if c.score(label_field) >= 90),
        # Stage 4 reviews 90+ clips and can lower the score later; the gate is still judged on Stage 3.
        "n_90_plus_lowered_by_stage4": sum(1 for c in labeled if lowered_by_stage4(c)),
        "n_90_plus_lowered_below_90_by_stage4": sum(
            1 for c in labeled if lowered_by_stage4(c) and (c.score("final_overall") or 0) < 90
        ),
        "weighted_share_below_40": share(lambda y: y < 40),
        "weighted_share_80_plus": share(lambda y: y >= 80),
    }


# --------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------


def pct(value) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def num(value, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def money(value) -> str:
    if value is None:
        return "unknown"
    return f"-${-value:,.2f}" if value < 0 else f"${value:,.2f}"


def per_clip(value) -> str:
    return "unknown" if value is None else f"${value:.5f}"


def with_ci(metric: dict | None) -> str:
    if not metric:
        return "n/a"
    text = pct(metric["value"])
    if metric.get("lo") is not None:
        text += f" ({pct(metric['lo'])} to {pct(metric['hi'])})"
    return text


def recall_cell(metrics: dict | None, cutoff: int) -> str:
    """Weighted recall with its bootstrap CI, the positive count and the one-sided 95% lower bound."""
    if not metrics:
        return "n/a"
    value = metrics[f"recall_{cutoff}"]
    count = metrics[f"n_{cutoff}"]
    lb = metrics[f"recall_{cutoff}_lb95"]
    if isinstance(value, dict):
        value, count, lb = value, count["value"], lb["value"]
        text = with_ci(value)
    else:
        text = pct(value)
    return f"{text} [n={count}, LB {pct(lb)}]"


def _table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines + [""]


def _run_label(run: dict) -> str:
    return run["id"] + (" (web)" if run.get("web_grounded") else "")


def _all_scorers(report: dict):
    for run in report["runs"]:
        for s in run["scorers"]:
            yield _run_label(run), s
    for s in report["baselines"]:
        yield "baseline", s


def _lost(main: dict | None) -> str:
    if not main:
        return "n/a"
    return f"{main['n_lost_90']['value']} / {main['n_lost_80']['value']}"


def _threshold(t) -> str:
    return "none (skip 0)" if t is None else f"{t:.3f}"


def _best(scorers: list[dict]) -> dict | None:
    candidates = [s for s in scorers if _pooled_skip(s) is not None]
    return max(candidates, key=lambda s: (_pooled_skip(s), s["name"]), default=None)


def _yes_no(value) -> str:
    return {True: "yes", False: "no", None: "n/a"}[value]


def render_markdown(report: dict) -> str:
    cfg, ds = report["config"], report["dataset"]
    out = [
        "# Decision-model pre-check evaluation (VER-475)",
        "",
        f"Generated {cfg['generated_at']}. Answer key: `label.{cfg['label_field']}`. "
        f"Bootstrap: {cfg['bootstrap']} resamples, seed {cfg['seed']}.",
        "",
        f"Bar: keep {pct(cfg['bar']['recall_90'])} of 90+ clips and at least {pct(cfg['bar']['recall_80'])} of "
        "80+ clips (weighted). A clip is skipped when its score is below the threshold picked on the other split. "
        f"Missing answers are never skipped. The strict point needs {pct(cfg['strict_recall_80'])} of 80+ on the "
        "threshold split.",
        "",
        "Recall cells read: weighted recall (bootstrap 95% CI) [n = positive clips, LB = one-sided 95% "
        "Clopper-Pearson lower bound from unweighted counts]. Runs marked (web) are web-grounded: a separate arm "
        "that checks claims against live web results, not a like-for-like text classifier.",
        "",
        "## Dataset",
        "",
    ]
    out += _table(
        ["Clips", "Labeled", "Dev", "Test", "80+ clips", "90+ clips", "90+ later lowered by Stage 4",
         "Weighted share < 40", "Weighted share 80+"],
        [[ds["n_clips"], ds["n_labeled"], ds["n_dev"], ds["n_test"], ds["n_80_plus"], ds["n_90_plus"],
          f"{ds['n_90_plus_lowered_by_stage4']} ({ds['n_90_plus_lowered_below_90_by_stage4']} below 90)",
          pct(ds["weighted_share_below_40"]), pct(ds["weighted_share_80_plus"])]],
    )
    if report["notes"]:
        out += ["Notes:", ""] + [f"- {n}" for n in report["notes"]] + [""]

    out += ["## Pick on dev, measure on test", ""]
    rows = []
    for rid, s in _all_scorers(report):
        d = s["directions"]["dev->test"]
        main = d["main"]
        rows.append([rid, s["name"], _threshold(d["threshold"]), with_ci((main or {}).get("skip_rate")),
                     recall_cell(main, 90), recall_cell(main, 80), _lost(main), _yes_no(s["passes_bar"]),
                     d["n_missing_eval"]])
    out += _table(["Run", "Scorer", "Threshold", "Skip rate", "Recall 90+", "Recall 80+", "Lost 90+ / 80+",
                   "Meets bar", "Missing"], rows)

    out += ["## Swapped: pick on test, measure on dev", ""]
    rows = []
    for rid, s in _all_scorers(report):
        d = s["directions"]["test->dev"]
        main = d["main"]
        rows.append([rid, s["name"], _threshold(d["threshold"]), with_ci((main or {}).get("skip_rate")),
                     recall_cell(main, 90), recall_cell(main, 80), _lost(main)])
    out += _table(["Run", "Scorer", "Threshold", "Skip rate", "Recall 90+", "Recall 80+", "Lost 90+ / 80+"], rows)

    out += ["## Pooled 2-fold cross-fit", ""]
    rows = []
    for rid, s in _all_scorers(report):
        p, ps = s["pooled"]["main"], s["pooled"]["strict"]
        rows.append([rid, s["name"], with_ci((p or {}).get("skip_rate")), recall_cell(p, 90), recall_cell(p, 80),
                     _lost(p), with_ci((ps or {}).get("skip_rate")), recall_cell(ps, 80),
                     num(s["auroc_80_vs_lt40"]), num(s["auroc_80_vs_rest"])])
    out += _table(["Run", "Scorer", "Skip rate", "Recall 90+", "Recall 80+", "Lost 90+ / 80+", "Strict skip rate",
                   "Strict recall 80+", "AUROC 80+ vs <40", "AUROC 80+ vs rest"], rows)

    out += ["## Recall when skipping the lowest-scored clips (pooled, threshold-free)", "",
            "Each cell is recall of 80+ / recall of 90+ at that weighted skip rate. Ties are skipped together, so "
            "the rate reached can fall short of the target; it is shown in brackets when it does.", ""]
    rows = []
    for rid, s in _all_scorers(report):
        cells = []
        for r in s["recall_at_skip"]:
            cell = f"{pct(r['recall_80'])} / {pct(r['recall_90'])}"
            if r["skip_rate"] is not None and r["target"] - r["skip_rate"] > 0.01:
                cell += f" [{pct(r['skip_rate'])}]"
            cells.append(cell)
        rows.append([rid, s["name"], *cells])
    out += _table(["Run", "Scorer", *[f"Skip {int(r * 100)}%" for r in SKIP_RATE_GRID]], rows)

    out += ["## What the skipped clips scored in Stage 3 (dev to test)", "",
            "Weighted share of skipped clips in each Stage 3 band.", ""]
    rows = []
    band_names = [band_name(i) for i in range(len(SCORE_BANDS))]
    for rid, s in _all_scorers(report):
        main = s["directions"]["dev->test"]["main"] or {}
        rows.append([rid, s["name"], *[with_ci(main.get(f"skipped_share_{b}")) for b in band_names]])
    out += _table(["Run", "Scorer", *band_names], rows)

    out += ["## Cost and speed", "",
            f"Vendor cut suspected: calls billed for under {pct(TRUNCATION_SUSPECT_RATIO)} of the estimated request "
            "tokens (Workers AI is reported to read only about the first 2,000 tokens of text state). Web-grounded "
            "runs bill retrieved evidence too, so their input tokens run high.", ""]
    rows = []
    for run in report["runs"]:
        c = run["cost"]
        q = c["input_tokens_quantiles"]
        rows.append([_run_label(run), run["n_clips"], num(c["repeats_per_clip"], 1), num(c["mean_input_tokens"], 0),
                     " / ".join(num(q[k], 0) for k in ("min", "p10", "p50", "p90", "max")),
                     c["suspected_vendor_truncation"], per_clip(c["cost_per_clip"]), num(c["latency_p50"], 2),
                     num(c["latency_p95"], 2), f"{c['errors']} ({pct(c['error_rate'])})",
                     f"{c['refusals']} ({pct(c['refusal_rate'])})", pct(c["missing_answer_rate"]),
                     c["truncated_states"], num(c["mean_citations"], 1)])
    out += _table(["Run", "Clips", "Calls per clip", "Mean input tokens", "Input tokens min / p10 / p50 / p90 / max",
                   "Vendor cut suspected", "$ per clip", "Latency p50 (s)", "Latency p95 (s)", "Errors",
                   "Refused answers", "Missing answers", "States cut by harness", "Mean citations"], rows)

    spread_rows = [[_run_label(run), q, v["clips"], num(v["mean"]), num(v["max"])]
                   for run in report["runs"] for q, v in run["repeat_spread"].items()]
    if spread_rows:
        out += ["## Spread across repeated calls", "",
                "Max minus min of each question's score across repeats of the same clip. The scorers use the mean.",
                ""]
        out += _table(["Run", "Question", "Clips", "Mean spread", "Max spread"], spread_rows)

    out += ["## Savings per day", "",
            f"{cfg['clips_per_day']} clips a day. Pooled skip rate of each run's best scorer, net of running the "
            "pre-check on every clip.", ""]
    rows = []
    stage3_models = list(cfg["stage3_costs"])
    best_rows = [(_run_label(run), _best(run["scorers"])) for run in report["runs"]]
    best_rows += [("baseline", s) for s in report["baselines"] if s["name"] != "always_run"]
    for rid, s in best_rows:
        if s is None:
            continue
        rows.append([rid, s["name"], pct(_pooled_skip(s)),
                     *[money(s["savings_per_day"].get(model)) for model in stage3_models]])
    out += _table(["Run", "Scorer", "Skip rate",
                   *[f"Saved/day at ${cfg['stage3_costs'][mo]} ({mo})" for mo in stage3_models]], rows)

    out += ["## Breakdowns (pooled cross-fit, best scorer per run)", "",
            "Cohort is Stage 3 model and traffic type together: they are confounded in this data.", ""]
    for rid, s in best_rows:
        if s is None:
            continue
        out += [f"### {rid}: {s['name']}", ""]
        for dim, groups in s["breakdowns"].items():
            rows = [[dim, key, g["n"], pct(g["weight_share"]), pct(g["skip_rate"]), recall_cell(g, 90),
                     recall_cell(g, 80), f"{g['n_lost_90']} / {g['n_lost_80']}"]
                    for key, g in sorted(groups.items(), key=lambda kv: (-kv[1]["n"], kv[0]))]
            out += _table(["Dimension", "Group", "Clips", "Weight share", "Skip rate", "Recall 90+", "Recall 80+",
                           "Lost 90+ / 80+"], rows)
    return "\n".join(out).rstrip() + "\n"
