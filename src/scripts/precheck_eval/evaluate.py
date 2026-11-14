"""Turn cached decision results and baselines into gate scorers and evaluate them (no network).

Directions: ``dev->test`` picks the threshold on dev and measures on test, ``test->dev`` the reverse,
and ``pooled`` (2-fold cross-fit) combines both measured halves so every clip is judged by a threshold
picked on the other split. Fitted scorers (the stacked model and the baselines) are trained on the
threshold split only; their scores on that split are out-of-fold (``CV_FOLDS``-fold) so the threshold is
not picked on in-sample predictions.
"""

import math
import re
import zlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from . import metrics as m
from .config import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    RECALL_BAR,
    SKIP_RATE_GRID,
    STRICT_RECALL_80,
    TOP_STATIONS,
    TRUNCATION_SUSPECT_RATIO,
)
from .dataset import Clip, model_input
from .logreg import Features, fit_logistic, fold_of
from .providers import parse_payload
from .variants import build_state, scorer_values, stack_features

CV_FOLDS = 5
POSITIVE_CUTOFF = 80  # fitted scorers learn P(stage3_overall >= 80)
HASH_DIM = 2**18
TEXT_EPOCHS = 30
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass
class Scorer:
    name: str
    kind: str  # "fixed" or "fitted"
    values: dict | None = None  # fixed: snippet_id -> float | None
    featurizer: Callable | None = None  # fitted: train clips -> (clip -> Features | None)
    standardize: bool = False
    l2: float = 1.0
    epochs: int = 40


@dataclass
class EvalOptions:
    label_field: str = "stage3_overall"
    bootstrap: int = BOOTSTRAP_SAMPLES
    seed: int = BOOTSTRAP_SEED
    min_recall_80: float = RECALL_BAR["recall_80"]
    min_recall_90: float = RECALL_BAR["recall_90"]
    strict_recall_80: float = STRICT_RECALL_80
    top_stations: int = TOP_STATIONS


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


def _fit_and_score(scorer: Scorer, train: list[Clip], target: list[Clip], label_field: str, seed: int):
    featurize = scorer.featurizer(train)
    rows = [(featurize(c), c) for c in train]
    rows = [(x, c) for x, c in rows if x is not None]
    X = [x for x, _ in rows]
    y = [1.0 if (c.score(label_field) or 0) >= POSITIVE_CUTOFF else 0.0 for _, c in rows]
    model = fit_logistic(X, y, l2=scorer.l2, epochs=scorer.epochs, seed=seed, standardize=scorer.standardize)
    out = []
    for c in target:
        x = featurize(c)
        out.append(None if x is None else model.predict(x))
    return out


def directional_scores(scorer: Scorer, fit: list[Clip], held: list[Clip], label_field: str, seed: int = 0):
    """(scores on the threshold split, scores on the held-out split)."""
    if scorer.kind == "fixed":
        return [scorer.values.get(c.snippet_id) for c in fit], [scorer.values.get(c.snippet_id) for c in held]
    fit_scores: list = [None] * len(fit)
    for fold in range(CV_FOLDS):
        inner = [c for c in fit if fold_of(c.snippet_id, CV_FOLDS) != fold]
        outer = [i for i, c in enumerate(fit) if fold_of(c.snippet_id, CV_FOLDS) == fold]
        if not outer:
            continue
        scored = _fit_and_score(scorer, inner, [fit[i] for i in outer], label_field, seed)
        for i, s in zip(outer, scored, strict=True):
            fit_scores[i] = s
    held_scores = _fit_and_score(scorer, fit, held, label_field, seed) if held else []
    return fit_scores, held_scores


def evaluate_scorer(scorer: Scorer, clips: list[Clip], opts: EvalOptions) -> dict:
    clips = [c for c in clips if c.score(opts.label_field) is not None]
    dev = [c for c in clips if c.split == "dev"]
    test = [c for c in clips if c.split == "test"]
    result: dict = {"name": scorer.name, "kind": scorer.kind, "directions": {}}
    pooled_skip: dict[str, list] = {"main": [], "strict": []}
    pooled_clips: list[Clip] = []
    pooled_scores: list = []
    for direction, fit, held in (("dev->test", dev, test), ("test->dev", test, dev)):
        fit_scores, held_scores = directional_scores(scorer, fit, held, opts.label_field, opts.seed)
        fit_labels = [c.score(opts.label_field) for c in fit]
        fit_weights = [c.weight for c in fit]
        held_labels = [c.score(opts.label_field) for c in held]
        held_weights = [c.weight for c in held]
        t_main = m.select_threshold(fit_scores, fit_labels, fit_weights, opts.min_recall_80, opts.min_recall_90)
        t_strict = m.select_threshold(fit_scores, fit_labels, fit_weights, opts.strict_recall_80, opts.min_recall_90)
        entry = {
            "n_fit": len(fit),
            "n_eval": len(held),
            "n_missing_eval": sum(1 for s in held_scores if s is None),
            "threshold": t_main,
            "threshold_strict": t_strict,
            "fit_skip_rate": m.point_metrics(
                [m.is_skipped(s, t_main) for s in fit_scores], fit_labels, fit_weights
            )["skip_rate"],
        }
        for key, t in (("main", t_main), ("strict", t_strict)):
            skipped = [m.is_skipped(s, t) for s in held_scores]
            entry[key] = (
                m.metrics_with_ci(skipped, held_labels, held_weights, opts.bootstrap, opts.seed) if held else None
            )
            pooled_skip[key] += skipped
        result["directions"][direction] = entry
        pooled_clips += held
        pooled_scores += held_scores
    labels = [c.score(opts.label_field) for c in pooled_clips]
    weights = [c.weight for c in pooled_clips]
    result["pooled"] = {
        key: m.metrics_with_ci(pooled_skip[key], labels, weights, opts.bootstrap, opts.seed) if pooled_clips else None
        for key in ("main", "strict")
    }
    result["n_missing"] = sum(1 for s in pooled_scores if s is None)
    result["auroc_80_vs_lt40"] = m.weighted_auroc(pooled_scores, labels, weights, lambda y: y >= 80, lambda y: y < 40)
    result["auroc_80_vs_rest"] = m.weighted_auroc(pooled_scores, labels, weights, lambda y: y >= 80, lambda y: y < 80)
    result["recall_at_skip"] = m.recall_at_skip_rates(pooled_scores, labels, weights, SKIP_RATE_GRID)
    result["passes_bar"] = _passes(result["directions"]["dev->test"]["main"], opts)
    result["breakdowns"] = breakdowns(pooled_clips, pooled_skip["main"], labels, weights, opts.top_stations)
    return result


def _passes(main: dict | None, opts: EvalOptions) -> bool | None:
    if not main:
        return None
    r90, r80 = main["recall_90"]["value"], main["recall_80"]["value"]
    return (r90 is None or r90 >= opts.min_recall_90 - m.EPS) and (r80 is None or r80 >= opts.min_recall_80 - m.EPS)


def breakdowns(clips: list[Clip], skipped, labels, weights, top_stations: int) -> dict:
    station_counts: dict[str, int] = {}
    for c in clips:
        code = str(c.meta.get("station_code") or "unknown")
        station_counts[code] = station_counts.get(code, 0) + 1
    top = {s for s, _ in sorted(station_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_stations]}
    keyers = {
        "stratum": lambda c: c.stratum or "unknown",
        "cohort": cohort,
        "analyzed_by": lambda c: str(c.label.get("analyzed_by") or "unknown"),
        "stage3_language": lambda c: str(c.meta.get("stage3_language") or "unknown"),
        "live": lambda c: str(c.meta.get("live")) if c.meta.get("live") is not None else "unknown",
        "station": lambda c: (code if (code := str(c.meta.get("station_code") or "unknown")) in top else "other"),
    }
    return {name: m.group_metrics(skipped, labels, weights, [f(c) for c in clips]) for name, f in keyers.items()}


def cohort(clip: Clip) -> str:
    """Stage 3 model x traffic type. They are confounded (3.8-flash is almost all live, 3.5-flash mostly
    re-queued backlog), so this view keeps them together instead of pretending to separate them."""
    model = str(clip.label.get("analyzed_by") or "unknown").replace("gemini-", "")
    live = clip.meta.get("live")
    traffic = "live" if live is True else "backlog" if live is False else "unknown"
    return f"{model} {traffic}"


# --------------------------------------------------------------------------------------
# Runs from the cache
# --------------------------------------------------------------------------------------


def run_id(record: dict) -> str:
    return f"{record['provider']}/{record['model']}/{record['variant']}"


def group_runs(records: list[dict], snippet_ids: set[str]) -> dict[str, dict[str, list[dict]]]:
    """run id -> snippet_id -> [latest record per repeat], restricted to clips in the dataset.

    Records written when a keyless route hit its rate limit are not results and are skipped.
    """
    latest: dict[str, dict[str, dict[int, dict]]] = {}
    for record in sorted(records, key=lambda r: str(r.get("created_at") or "")):
        if record.get("snippet_id") not in snippet_ids or record.get("rate_limited"):
            continue
        per_clip = latest.setdefault(run_id(record), {}).setdefault(record["snippet_id"], {})
        per_clip[int(record.get("repeat") or 0)] = record
    return {
        rid: {sid: [reps[k] for k in sorted(reps)] for sid, reps in clips.items()} for rid, clips in latest.items()
    }


def record_answers(record: dict) -> dict:
    """Re-normalize from the stored raw response so parser fixes apply without re-calling the vendor."""
    result = record.get("result") or {}
    questions = (record.get("request") or {}).get("questions") or {}
    status = result.get("http_status")
    if result.get("error") is not None and not (status and 200 <= status < 300):
        return {}
    raw = result.get("raw")
    if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and "jsonrpc" in raw:
        raw = raw["result"].get("structuredContent", raw)  # an MCP envelope stored as-is
    answers, _, _, error = parse_payload(raw, questions)
    return {} if error else answers


def merge_answers(answer_sets: list[dict]) -> dict:
    """Average repeated calls per question: mean value, mean probabilities; missing only if all are missing."""
    answer_sets = [a for a in answer_sets if a]
    if not answer_sets:
        return {}
    if len(answer_sets) == 1:
        return answer_sets[0]
    merged = {}
    for name in sorted({n for a in answer_sets for n in a}):
        present = [a[name] for a in answer_sets if name in a and not a[name].get("missing")]
        if not present:
            merged[name] = dict(next(a[name] for a in answer_sets if name in a))
            continue
        out = dict(present[0])
        values = [p["value"] for p in present if p.get("value") is not None]
        out["value"] = sum(values) / len(values) if values else None
        labels = {k for p in present for k in (p.get("probabilities") or {})}
        out["probabilities"] = {
            k: sum(float((p.get("probabilities") or {}).get(k) or 0.0) for p in present) / len(present)
            for k in sorted(labels)
        }
        if out["probabilities"]:
            out["choice"] = max(out["probabilities"], key=lambda k: (out["probabilities"][k], k))
        merged[name] = out
    return merged


def run_questions(run_records: dict[str, list[dict]]) -> dict:
    questions: dict = {}
    for records in run_records.values():
        for record in records:
            questions = (record.get("request") or {}).get("questions") or questions
    return questions


def run_scorers(run_records: dict[str, list[dict]]) -> list[Scorer]:
    questions = run_questions(run_records)
    answers = {sid: merge_answers([record_answers(r) for r in recs]) for sid, recs in run_records.items()}
    scorers = []
    for name in sorted(questions):
        values = {sid: scorer_values(a).get(name) if a else None for sid, a in answers.items()}
        scorers.append(Scorer(name=name, kind="fixed", values=values))

    def stacked_featurizer(_train):
        def featurize(clip):
            a = answers.get(clip.snippet_id)
            feats = stack_features(a, questions) if a else None
            return None if feats is None else dict(enumerate(feats))

        return featurize

    if questions:
        scorers.append(Scorer(name="stacked", kind="fitted", featurizer=stacked_featurizer, standardize=True))
    return scorers


def repeat_spread(run_records: dict[str, list[dict]]) -> dict:
    """Per question: mean and max (max - min) of the scorer value across repeats of the same clip."""
    spreads: dict[str, list[float]] = {}
    for records in run_records.values():
        if len(records) < 2:
            continue
        per_q: dict[str, list[float]] = {}
        for record in records:
            for name, value in scorer_values(record_answers(record)).items():
                if value is not None:
                    per_q.setdefault(name, []).append(value)
        for name, values in per_q.items():
            if len(values) >= 2:
                spreads.setdefault(name, []).append(max(values) - min(values))
    return {
        name: {"clips": len(v), "mean": sum(v) / len(v), "max": max(v)} for name, v in sorted(spreads.items())
    }


def run_cost(run_records: dict[str, list[dict]], price) -> dict:
    """Tokens, dollars, latency, errors, refusals and suspected vendor-side truncation for one run."""
    calls = [r for recs in run_records.values() for r in recs]
    n = len(calls)
    inputs, costs, latencies = [], [], []
    errors = refusals = missing = answers_total = truncated = suspected_cut = 0
    citations = []
    for record in calls:
        result = record.get("result") or {}
        latencies.append(float(result.get("latency_s") or 0.0))
        state_meta = record.get("state_meta") or {}
        if state_meta.get("truncated"):
            truncated += 1
        if result.get("error") is not None:
            errors += 1
            continue
        usage = result.get("usage") or {}
        billed = usage.get("input_tokens")
        if billed is not None:
            inputs.append(billed)
            expected = state_meta.get("est_request_tokens")
            if expected and billed < TRUNCATION_SUSPECT_RATIO * expected:
                suspected_cut += 1
        if "cost" in usage:
            costs.append(float(usage["cost"]))
        else:
            costs.append(price.cost(billed, usage.get("output_tokens")))
        citations.append(len(result.get("citations") or []))
        for answer in record_answers(record).values():
            answers_total += 1
            refusals += 1 if answer.get("refused") else 0
            missing += 1 if answer.get("missing") else 0
    known = [c for c in costs if c is not None]
    clips = len(run_records)
    return {
        "n_calls": n,
        "n_clips": clips,
        "repeats_per_clip": n / clips if clips else None,
        "errors": errors,
        "error_rate": errors / n if n else None,
        "refusals": refusals,
        "refusal_rate": refusals / answers_total if answers_total else None,
        "missing_answer_rate": missing / answers_total if answers_total else None,
        "mean_input_tokens": sum(inputs) / len(inputs) if inputs else None,
        "input_tokens_quantiles": {
            q: m.quantile(inputs, p) for q, p in (("min", 0.0), ("p10", 0.1), ("p50", 0.5), ("p90", 0.9), ("max", 1.0))
        },
        "suspected_vendor_truncation": suspected_cut,
        # Pre-check cost per clip: every repeat is a paid call.
        "cost_per_clip": (sum(known) / clips) if clips and known and len(known) == len(costs) else None,
        "latency_p50": m.quantile(latencies, 0.5),
        "latency_p95": m.quantile(latencies, 0.95),
        "truncated_states": truncated,
        "mean_citations": sum(citations) / len(citations) if citations else None,
    }


def savings(skip_rate: float | None, precheck_cost: float | None, stage3_costs: dict, clips_per_day: float) -> dict:
    """Dollars saved per day: skipped Stage 3 calls minus running the pre-check on every clip."""
    out = {}
    for model, cost in stage3_costs.items():
        if skip_rate is None or precheck_cost is None:
            out[model] = None
        else:
            out[model] = clips_per_day * (skip_rate * cost - precheck_cost)
    return out


# --------------------------------------------------------------------------------------
# Baselines (free classifiers trained on the answer key)
# --------------------------------------------------------------------------------------


def always_run_scorer(clips: list[Clip]) -> Scorer:
    return Scorer(name="always_run", kind="fixed", values={c.snippet_id: 1.0 for c in clips})


def _hour(recorded_at) -> str:
    if not recorded_at:
        return "unknown"
    try:
        return str(datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00")).hour)
    except ValueError:
        return "unknown"


def stage1_raw_features(clip: Clip) -> dict:
    """Simple pre-Stage-3 facts: Stage 1 output sizes and labels, station, hour, language guess, recording."""
    inp = clip.input
    extra = inp.get("stage1_extra") if isinstance(inp.get("stage1_extra"), dict) else {}
    cats = inp.get("stage1_categories") or []
    keywords = inp.get("stage1_keywords") or []

    def number(value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0

    return {
        "numeric": [
            float(len(cats)),
            float(len(keywords)),
            math.log1p(len(str(inp.get("stage1_transcript_excerpt") or ""))),
            math.log1p(len(str(extra.get("flagged_transcription") or ""))),
            math.log1p(number(inp.get("duration_s"))),
            number(extra.get("n_flagged_in_recording")),
        ],
        "tags": sorted(
            {f"cat={c}" for c in cats}
            | {
                f"station={clip.meta.get('station_code') or 'unknown'}",
                f"hour={_hour(clip.meta.get('recorded_at'))}",
                f"lang={inp.get('stage1_language') or 'unknown'}",
                f"s1prompt={str(extra.get('detection_prompt_version_id') or 'unknown')[:8]}",
            }
        ),
    }


N_NUMERIC_STAGE1 = 6


def stage1_featurizer(train: list[Clip]):
    vocab: dict[str, int] = {}
    for c in train:
        for tag in stage1_raw_features(c)["tags"]:
            vocab.setdefault(tag, N_NUMERIC_STAGE1 + len(vocab))

    def featurize(clip: Clip) -> Features:
        r = stage1_raw_features(clip)
        x = dict.fromkeys(range(N_NUMERIC_STAGE1 + len(vocab)), 0.0)  # dense, so standardization is consistent
        for i, value in enumerate(r["numeric"]):
            x[i] = value
        for tag in r["tags"]:
            if tag in vocab:
                x[vocab[tag]] = 1.0
        return x

    return featurize


def text_features(text: str, dim: int = HASH_DIM) -> Features:
    """Hashed word unigrams + bigrams with sublinear counts (1 + log n), L2-normalized.

    crc32, not ``hash()``, so features are stable across processes.
    """
    tokens = TOKEN_RE.findall(text.lower())
    grams = Counter(tokens) + Counter(f"{a} {b}" for a, b in zip(tokens, tokens[1:], strict=False))
    x: Features = {}
    for gram, count in grams.items():
        j = zlib.crc32(gram.encode()) % dim
        x[j] = x.get(j, 0.0) + 1.0 + math.log(count)
    norm = math.sqrt(sum(v * v for v in x.values()))
    return {j: v / norm for j, v in x.items()} if norm else {}


def text_featurizer_factory(variant: str = "full"):
    cache: dict[str, Features] = {}

    def featurizer(_train):
        def featurize(clip: Clip) -> Features:
            if clip.snippet_id not in cache:
                cache[clip.snippet_id] = text_features(build_state(model_input(clip), variant).text)
            return cache[clip.snippet_id]

        return featurize

    return featurizer


def baseline_scorers(clips: list[Clip], text_epochs: int = TEXT_EPOCHS) -> list[Scorer]:
    return [
        always_run_scorer(clips),
        Scorer(name="stage1_fields", kind="fitted", featurizer=stage1_featurizer, standardize=True),
        Scorer(name="text_lr", kind="fitted", featurizer=text_featurizer_factory(), l2=1.0, epochs=text_epochs),
    ]
