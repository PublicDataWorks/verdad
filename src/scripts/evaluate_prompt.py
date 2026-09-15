#!/usr/bin/env python3
"""
Evaluate a proposed Stage 3 prompt change against the active prompt before it is deployed.

For every selected snippet the harness assembles exactly the inputs Stage 3 uses (the
snippet row with its audio_file / stage_1 detection joins, the Stage 3 metadata block and the
audio clip from R2), runs ``Stage3Executor`` with the baseline and the candidate prompt K times
each, and compares the structured outputs. It is strictly read-only against Supabase: no
snippet, label, prompt version or any other row is written.

Usage (all flags optional unless noted):

    PYTHONPATH=.:src python src/scripts/evaluate_prompt.py \
        --candidate-dir prompts \
        --snippet-file prompts/eval/fabricated-content-false-positives-2026-09.json \
        --runs 2 --out eval-report.md --json results.json

    # Select snippets from analyst feedback plus a random control group instead of a file
    PYTHONPATH=.:src python src/scripts/evaluate_prompt.py --from-feedback --since 2026-08-01 --control 12

Snippet selection sources can be combined; ``--snippet-ids`` and ``--from-feedback`` count as
"reported" snippets, ``--control`` as control snippets, and ``--snippet-file`` contributes both.

Required environment: SUPABASE_URL, SUPABASE_KEY, GOOGLE_GEMINI_KEY, R2_ENDPOINT_URL,
R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME and SEARXNG_URL (the Stage 3 web tools).
"""

import argparse
import asyncio
import copy
import json
import os
import random
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import combinations

from dotenv import load_dotenv

# The Stage 3 helpers are Prefect tasks in production; run them as plain functions here.
os.environ["ENABLE_PREFECT_DECORATOR"] = "false"

from processing_pipeline.constants import PromptStage  # noqa: E402
from processing_pipeline.stage_3.constants import MAIN_MODEL  # noqa: E402
from processing_pipeline.stage_3.executors import Stage3Executor  # noqa: E402
from processing_pipeline.stage_3.tasks import fetch_a_specific_snippet_from_supabase, get_metadata  # noqa: E402
from processing_pipeline.supabase_utils import SupabaseClient  # noqa: E402
from src.scripts.prompt_manifest import load_manifest, read_prompt_files, resolve_manifest_path  # noqa: E402

load_dotenv()

STAGE_3_LABEL = "stage_3"
DEFAULT_THRESHOLD = 70
DEFAULT_RUNS = 2
DEFAULT_CONCURRENCY = 2
# Gemini SDK retry policy for 429 / 5xx responses (exponential backoff, seconds).
RETRY_ATTEMPTS = 5
RETRY_INITIAL_DELAY = 2
RETRY_MAX_DELAY = 60
FAILURE_EXAMPLE_CHARS = 300
FLAG_ON_CHOICES = ("overall", "category")
EVIDENCE_CHARS = 300
MISSING_ENV_EXIT_CODE = 2
REQUIRED_ENV = (
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "GOOGLE_GEMINI_KEY",
    "R2_ENDPOINT_URL",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)

# USD per 1M tokens for the paid tier, prompts <= 200k tokens. Output includes thinking tokens.
# UPDATE THESE when Google changes pricing: https://ai.google.dev/gemini-api/docs/pricing
MODEL_PRICES_PER_M_TOKENS = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
}

REPORTED = "reported"
CONTROL = "control"


# --------------------------------------------------------------------------------------
# Pure classification / aggregation (unit-tested, no network)
# --------------------------------------------------------------------------------------


@dataclass
class RunResult:
    """One Stage 3 model output reduced to the fields the harness compares."""

    categories: list[str] = field(default_factory=list)
    overall: int | None = None
    category_scores: dict[str, int] = field(default_factory=dict)
    verification_status: str | None = None
    explanation: str = ""
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None
    cap_reasons: list[str] = field(default_factory=list)  # evidence gate reasons; empty when no cap applied

    @property
    def ok(self) -> bool:
        return self.error is None


def cap_reasons_from(response: dict, grounding_metadata=None) -> list[str]:
    """The evidence gate's reasons for a run, or ``[]`` when no cap applied or the record lacks the field.

    The executor pops ``evidence_gate`` out of the output into the ``grounding_metadata`` JSON string (only
    when a cap applied); older records have no such key, and an output that still carries ``evidence_gate``
    inline is read too.
    """
    if isinstance(grounding_metadata, str):
        try:
            grounding_metadata = json.loads(grounding_metadata)
        except ValueError:
            grounding_metadata = None
    for container in (grounding_metadata, response):
        gate = container.get("evidence_gate") if isinstance(container, dict) else None
        if isinstance(gate, dict):
            return [str(r) for r in gate.get("reasons") or [] if r]
    return []


def parse_output(response: dict, grounding_metadata=None) -> RunResult:
    """Reduce a validated Stage 3 output dict to a :class:`RunResult`.

    ``grounding_metadata`` is the executor's JSON string (or parsed dict) holding the evidence gate record.
    """
    scores = response.get("confidence_scores") or {}
    categories = []
    for item in response.get("disinformation_categories") or []:
        name = item.get("english") if isinstance(item, dict) else item
        if name:
            categories.append(str(name).strip())
    category_scores = {}
    for item in scores.get("categories") or []:
        if isinstance(item, dict) and item.get("category"):
            category_scores[str(item["category"]).strip()] = int(item.get("score") or 0)
    explanation = response.get("explanation") or {}
    if isinstance(explanation, dict):
        explanation = explanation.get("english") or explanation.get("spanish") or ""
    return RunResult(
        categories=sorted(set(categories)),
        overall=scores.get("overall"),
        category_scores=category_scores,
        verification_status=scores.get("verification_status"),
        explanation=str(explanation),
        cap_reasons=cap_reasons_from(response, grounding_metadata),
    )


def confidence(run: RunResult, flag_on: str = "overall") -> int:
    """The score the flag decision is based on: ``overall`` or the highest per-category score."""
    if flag_on == "category":
        return max(run.category_scores.values(), default=0)
    return int(run.overall or 0)


def is_flagged(run: RunResult, threshold: int = DEFAULT_THRESHOLD, flag_on: str = "overall") -> bool:
    return run.ok and confidence(run, flag_on) >= threshold


def majority(values: list[bool]) -> bool:
    """Strict majority; ties (e.g. 1 of 2 runs) count as False."""
    return sum(1 for v in values if v) * 2 > len(values)


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@dataclass
class RunSummary:
    """Majority-vote view over the K runs of one prompt on one snippet."""

    n_runs: int = 0
    n_ok: int = 0
    flagged: bool = False
    flag_agreement: float = 1.0  # share of successful runs agreeing with the majority flag
    mean_confidence: float = 0.0
    categories: list[str] = field(default_factory=list)  # categories present in a majority of runs
    category_stability: float = 1.0  # mean pairwise Jaccard of category sets across runs
    verification_statuses: list[str] = field(default_factory=list)
    explanation: str = ""  # explanation of a representative (majority-side) run
    errors: list[str] = field(default_factory=list)


def summarize_runs(runs: list[RunResult], threshold: int = DEFAULT_THRESHOLD, flag_on: str = "overall") -> RunSummary:
    ok_runs = [r for r in runs if r.ok]
    summary = RunSummary(n_runs=len(runs), n_ok=len(ok_runs), errors=[r.error for r in runs if r.error])
    if not ok_runs:
        return summary

    flags = [is_flagged(r, threshold, flag_on) for r in ok_runs]
    summary.flagged = majority(flags)
    summary.flag_agreement = max(sum(flags), len(flags) - sum(flags)) / len(flags)
    summary.mean_confidence = _mean(confidence(r, flag_on) for r in ok_runs)

    counts: dict[str, int] = {}
    for r in ok_runs:
        for c in r.categories:
            counts[c] = counts.get(c, 0) + 1
    summary.categories = sorted(c for c, n in counts.items() if n * 2 > len(ok_runs))

    pairs = list(combinations(ok_runs, 2))
    summary.category_stability = _mean(jaccard(a.categories, b.categories) for a, b in pairs) if pairs else 1.0
    summary.verification_statuses = sorted({r.verification_status for r in ok_runs if r.verification_status})

    representative = next((r for r, f in zip(ok_runs, flags) if f == summary.flagged), ok_runs[0])
    summary.explanation = representative.explanation
    return summary


# Verdict labels. Reported snippets are analyst-reported false positives we want the candidate
# to stop flagging; control snippets are liked, un-disliked detections we want it to keep.
FIXED = "fixed"
UNCHANGED = "unchanged"
NOT_FLAGGED_BY_BASELINE = "not flagged by baseline"
NEWLY_FLAGGED = "newly flagged"
KEPT = "kept"
LOST = "lost"
NO_DATA = "no data"


def snippet_verdict(kind: str, baseline: RunSummary, candidate: RunSummary) -> str:
    if not baseline.n_ok or not candidate.n_ok:
        return NO_DATA
    if baseline.flagged and not candidate.flagged:
        return FIXED if kind == REPORTED else LOST
    if baseline.flagged and candidate.flagged:
        return UNCHANGED if kind == REPORTED else KEPT
    if not baseline.flagged and candidate.flagged:
        return NEWLY_FLAGGED
    return NOT_FLAGGED_BY_BASELINE


@dataclass
class SnippetResult:
    snippet_id: str
    kind: str
    title: str = ""
    baseline_runs: list[RunResult] = field(default_factory=list)
    candidate_runs: list[RunResult] = field(default_factory=list)
    baseline: RunSummary = field(default_factory=RunSummary)
    candidate: RunSummary = field(default_factory=RunSummary)
    verdict: str = NO_DATA
    error: str | None = None  # data assembly failure (snippet missing, audio download failed, ...)

    def finalize(self, threshold: int, flag_on: str) -> "SnippetResult":
        self.baseline = summarize_runs(self.baseline_runs, threshold, flag_on)
        self.candidate = summarize_runs(self.candidate_runs, threshold, flag_on)
        self.verdict = snippet_verdict(self.kind, self.baseline, self.candidate)
        return self


def sum_usage(runs: list[RunResult]) -> dict:
    totals: dict[str, int] = {}
    for r in runs:
        for k, v in (r.usage or {}).items():
            totals[k] = totals.get(k, 0) + int(v or 0)
    return totals


def estimate_cost(usage: dict, model: str) -> float | None:
    """USD estimate from token totals; None when the model has no price entry."""
    prices = MODEL_PRICES_PER_M_TOKENS.get(str(model))
    if not prices:
        return None
    input_tokens = usage.get("prompt_token_count", 0) + usage.get("tool_use_prompt_token_count", 0)
    output_tokens = usage.get("candidates_token_count", 0) + usage.get("thoughts_token_count", 0)
    return (input_tokens * prices["input"] + output_tokens * prices["output"]) / 1_000_000


def aggregate(results: list[SnippetResult], model: str) -> dict:
    reported = [r for r in results if r.kind == REPORTED]
    control = [r for r in results if r.kind == CONTROL]
    evaluated = [r for r in results if r.verdict != NO_DATA]

    def count(rs, verdict):
        return sum(1 for r in rs if r.verdict == verdict)

    all_runs = [run for r in results for run in r.baseline_runs + r.candidate_runs]
    usage = sum_usage(all_runs)
    return {
        "reported_total": len(reported),
        "control_total": len(control),
        "evaluated": len(evaluated),
        "no_data": len(results) - len(evaluated),
        "false_positives_fixed": count(reported, FIXED),
        "reported_unchanged": count(reported, UNCHANGED),
        "reported_not_flagged_by_baseline": count(reported, NOT_FLAGGED_BY_BASELINE),
        "reported_newly_flagged": count(reported, NEWLY_FLAGGED),
        "true_positives_lost": count(control, LOST),
        "control_kept": count(control, KEPT),
        "control_not_flagged_by_baseline": count(control, NOT_FLAGGED_BY_BASELINE),
        "control_newly_flagged": count(control, NEWLY_FLAGGED),
        "mean_confidence_shift": _mean(r.candidate.mean_confidence - r.baseline.mean_confidence for r in evaluated),
        "label_churn": _mean(1 - jaccard(r.baseline.categories, r.candidate.categories) for r in evaluated),
        "baseline_flag_agreement": _mean(r.baseline.flag_agreement for r in evaluated),
        "candidate_flag_agreement": _mean(r.candidate.flag_agreement for r in evaluated),
        "runs_total": len(all_runs),
        "runs_failed": sum(1 for run in all_runs if not run.ok),
        "usage": usage,
        "estimated_cost_usd": estimate_cost(usage, model),
        "model_runtime_seconds": sum(run.seconds for run in all_runs),
    }


def failure_histogram(results: list[SnippetResult]) -> list[dict]:
    """Failed model calls grouped by exception class (the text before the first colon), most frequent first."""
    buckets: dict[str, dict] = {}
    for r in results:
        for side, runs in (("baseline", r.baseline_runs), ("candidate", r.candidate_runs)):
            for run in runs:
                if run.ok:
                    continue
                error = run.error or "unknown error"
                kind = error.split(":", 1)[0].strip() or "unknown error"
                bucket = buckets.setdefault(
                    kind, {"kind": kind, "count": 0, "example": error, "snippet_id": r.snippet_id, "side": side}
                )
                bucket["count"] += 1
    return sorted(buckets.values(), key=lambda b: (-b["count"], b["kind"]))


def cap_histogram(results: list[SnippetResult]) -> list[dict]:
    """Successful runs capped by the evidence gate, counted per reason and arm, most frequent first."""
    buckets: dict[str, dict] = {}
    for r in results:
        for side, runs in (("baseline", r.baseline_runs), ("candidate", r.candidate_runs)):
            for run in runs:
                if not run.ok:
                    continue
                for reason in run.cap_reasons:
                    bucket = buckets.setdefault(reason, {"reason": reason, "baseline": 0, "candidate": 0})
                    bucket[side] += 1
    return sorted(buckets.values(), key=lambda b: (-(b["baseline"] + b["candidate"]), b["reason"]))


def _fmt_categories(summary: RunSummary) -> str:
    if not summary.n_ok:
        return "error" if summary.errors else "-"
    cats = ", ".join(summary.categories) if summary.categories else "none"
    return f"{cats} ({summary.mean_confidence:.0f})"


def _md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render_report(results: list[SnippetResult], agg: dict, config: dict, notes: list[str] | None = None) -> str:
    cost = agg["estimated_cost_usd"]
    cost_str = f"${cost:.2f}" if cost is not None else f"n/a (no price for {config['model']})"
    lines = [
        "# Prompt evaluation report: Stage 3",
        "",
        f"- Generated: {config.get('generated_at', '')}",
        f"- Baseline: {config['baseline']}",
        f"- Candidate: {config['candidate']}",
        f"- Model: {config['model']} | runs per prompt: {config['runs']} | flag threshold: "
        f"{config['threshold']} on `{config['flag_on']}`",
        f"- Snippets: {agg['reported_total']} reported, {agg['control_total']} control "
        f"({agg['no_data']} without usable results)",
        f"- Model calls: {agg['runs_total']} ({agg['runs_failed']} failed) | tokens: "
        f"{agg['usage'].get('total_token_count', 0):,} | estimated cost: {cost_str} | "
        f"model time: {agg['model_runtime_seconds'] / 60:.1f} min | wall time: "
        f"{config.get('wall_seconds', 0) / 60:.1f} min",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| False positives fixed (reported: flagged by baseline, not by candidate) | "
        f"{agg['false_positives_fixed']} / {agg['reported_total']} |",
        f"| Reported still flagged | {agg['reported_unchanged']} |",
        f"| Reported not flagged by baseline either | {agg['reported_not_flagged_by_baseline']} |",
        f"| Reported newly flagged by candidate | {agg['reported_newly_flagged']} |",
        f"| True positives lost (control: flagged by baseline, not by candidate) | "
        f"{agg['true_positives_lost']} / {agg['control_total']} |",
        f"| Control kept | {agg['control_kept']} |",
        f"| Control not flagged by baseline | {agg['control_not_flagged_by_baseline']} |",
        f"| Control newly flagged by candidate | {agg['control_newly_flagged']} |",
        f"| Mean confidence shift (candidate - baseline) | {agg['mean_confidence_shift']:+.1f} |",
        f"| Label churn (1 - Jaccard of majority categories) | {agg['label_churn']:.2f} |",
        f"| Flag stability baseline / candidate | {agg['baseline_flag_agreement']:.2f} / "
        f"{agg['candidate_flag_agreement']:.2f} |",
        "",
        "## Per-snippet results",
        "",
        "| Snippet | Set | Title | Baseline categories (conf) | Candidate categories (conf) | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        verdict = r.verdict if not r.error else f"error: {_md(r.error)[:80]}"
        lines.append(
            f"| `{r.snippet_id[:8]}` | {r.kind} | {_md(r.title)[:60]} | {_md(_fmt_categories(r.baseline))} | "
            f"{_md(_fmt_categories(r.candidate))} | {verdict} |"
        )

    fixed = [r for r in results if r.verdict == FIXED]
    lines += ["", "## Evidence", ""]
    if not fixed:
        lines.append("No reported snippet changed from flagged to not flagged.")
    for r in fixed:
        quote = _md(r.candidate.explanation)[:EVIDENCE_CHARS]
        lines += [f"### `{r.snippet_id}` {_md(r.title)}".rstrip(), "", f"> {quote}", ""]

    lost = [r for r in results if r.verdict == LOST]
    if lost:
        lines += ["## Regressions", ""]
        for r in lost:
            quote = _md(r.candidate.explanation)[:EVIDENCE_CHARS]
            lines += [f"### `{r.snippet_id}` {_md(r.title)}".rstrip(), "", f"> {quote}", ""]

    caps = cap_histogram(results)
    if caps:
        lines += [
            "## Capped runs by reason",
            "",
            "Successful model calls whose confidence the evidence gate clamped, by the reason it recorded.",
            "",
            "| Reason | Baseline runs | Candidate runs |",
            "|---|---|---|",
        ]
        for bucket in caps:
            lines.append(f"| {_md(bucket['reason'])} | {bucket['baseline']} | {bucket['candidate']} |")
        lines.append("")

    failures = failure_histogram(results)
    if failures:
        lines += [
            "## Failures",
            "",
            f"{agg['runs_failed']} of {agg['runs_total']} model calls failed. "
            "Failed calls are excluded from the per-snippet majority votes above.",
            "",
            "| Error | Count | Example |",
            "|---|---|---|",
        ]
        for bucket in failures:
            example = _md(bucket["example"])[:FAILURE_EXAMPLE_CHARS]
            where = f"`{bucket['snippet_id'][:8]}` {bucket['side']}"
            lines.append(f"| `{_md(bucket['kind'])}` | {bucket['count']} | {where}: {example} |")
        lines.append("")

    if notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------------------
# Snippet selection
# --------------------------------------------------------------------------------------


def load_snippet_file(path: str) -> tuple[list[str], list[str], str]:
    """Accept a bare JSON list of ids (all reported) or an eval-set object."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [str(x) for x in data], [], ""
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON list or an eval-set object")
    return (
        [str(x) for x in data.get("reported") or []],
        [str(x) for x in data.get("control") or []],
        str(data.get("description") or ""),
    )


def pick_control(candidate_ids: list[str], n: int, seed: int) -> list[str]:
    """Deterministic random sample (sorted input so DB row order does not matter)."""
    pool = sorted(set(candidate_ids))
    return random.Random(seed).sample(pool, min(n, len(pool)))


def dedupe(ids) -> list[str]:
    """Drop duplicates, keeping first-seen order."""
    return list(dict.fromkeys(ids))


# --------------------------------------------------------------------------------------
# Data access (read-only) and the Gemini wrapper
# --------------------------------------------------------------------------------------


class EvalDataSource:
    """Read-only access to Supabase and R2, mirroring the Stage 3 flow's data assembly."""

    def __init__(self, supabase_client: SupabaseClient, s3_client, bucket_name: str):
        self.supabase = supabase_client
        self.s3 = s3_client
        self.bucket = bucket_name

    @classmethod
    def from_env(cls):
        import boto3

        supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))
        s3_client = boto3.client(
            "s3",
            endpoint_url=os.getenv("R2_ENDPOINT_URL"),
            aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
        )
        return cls(supabase_client, s3_client, os.getenv("R2_BUCKET_NAME"))

    def active_prompt(self) -> dict:
        return self.supabase.get_active_prompt(PromptStage.STAGE_3)

    def prompt_by_id(self, prompt_version_id: str) -> dict:
        return self.supabase.get_prompt_by_id(prompt_version_id)

    def fetch_snippet(self, snippet_id: str) -> dict | None:
        # Same select (audio_file + stage_1 detection joins) as the Stage 3 flow.
        return fetch_a_specific_snippet_from_supabase(self.supabase, snippet_id)

    def download_audio(self, snippet: dict, dest_dir: str) -> str:
        local_path = os.path.join(dest_dir, os.path.basename(snippet["file_path"]))
        self.s3.download_file(self.bucket, snippet["file_path"], local_path)
        return local_path

    def feedback_snippet_ids(self, since: str) -> list[str]:
        """Snippets with a comment or a dislike since ``since`` (YYYY-MM-DD)."""
        since_iso = f"{since}T00:00:00+00:00"
        comments = (
            self.supabase.client.table("comments")
            .select("room_id")
            .gte("created_at", since_iso)
            .is_("deleted_at", "null")
            .execute()
        )
        dislikes = (
            self.supabase.client.table("user_like_snippets")
            .select("snippet")
            .eq("value", -1)
            .gte("created_at", since_iso)
            .execute()
        )
        ids = [row["room_id"] for row in comments.data or [] if row.get("room_id")]
        ids += [row["snippet"] for row in dislikes.data or [] if row.get("snippet")]
        return dedupe(ids)

    def control_candidate_ids(self, days: int = 90, limit: int = 1000) -> list[str]:
        """Processed, liked, never-disliked snippets recorded in the last ``days`` days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        response = (
            self.supabase.client.table("snippets")
            .select("id")
            .eq("status", "Processed")
            .eq("dislike_count", 0)
            .gt("like_count", 0)
            .gte("recorded_at", cutoff)
            .limit(limit)
            .execute()
        )
        return [row["id"] for row in response.data or []]


def client_http_options() -> dict:
    """``genai.Client`` kwargs enabling SDK-level retries; empty when the installed SDK lacks them.

    Four agentic conversations in flight with no retry lost more than half the calls of the first
    real run to 429/5xx. The SDK retries those status codes itself when asked.
    """
    try:
        from google.genai.types import HttpOptions, HttpRetryOptions

        retry = HttpRetryOptions(attempts=RETRY_ATTEMPTS, initial_delay=RETRY_INITIAL_DELAY, max_delay=RETRY_MAX_DELAY)
        return {"http_options": HttpOptions(retry_options=retry)}
    except (ImportError, TypeError, ValueError) as e:
        print(f"warning: google-genai retry options unavailable ({type(e).__name__}: {e}); no retries", flush=True)
        return {}


def describe_exception(e: BaseException, limit: int = 500) -> str:
    """``ClassName: message (at path/to/file.py:LINE)`` for the innermost frame, capped at ``limit`` characters.

    The location is kept when the message is truncated, so a failure stays locatable in the report."""
    frames = traceback.extract_tb(e.__traceback__)
    location = ""
    if frames:
        frame = frames[-1]
        location = f" (at {'/'.join(frame.filename.replace(os.sep, '/').split('/')[-3:])}:{frame.lineno})"
    message = f"{type(e).__name__}: {e}"
    return message[: max(limit - len(location), 0)] + location


class GeminiRunner:
    """Thin, mockable wrapper around the Stage 3 executor (no Supabase access)."""

    def __init__(self, gemini_client, model: str):
        self.client = gemini_client
        self.model = model

    @classmethod
    def from_env(cls, model: str):
        from google import genai

        return cls(genai.Client(api_key=os.getenv("GOOGLE_GEMINI_KEY"), **client_http_options()), model)

    async def run(self, prompt_version: dict, audio_file: str, metadata: dict) -> RunResult:
        started = time.monotonic()
        try:
            response = await Stage3Executor.run_async(
                gemini_client=self.client,
                model_name=self.model,
                audio_file=audio_file,
                metadata=copy.deepcopy(metadata),
                prompt_version=prompt_version,
            )
            result = parse_output(response["response"], response.get("grounding_metadata"))
            result.usage = response.get("usage") or {}
        except Exception as e:  # keep going; the failure is reported per run
            result = RunResult(error=describe_exception(e))
        result.seconds = time.monotonic() - started
        return result


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------


def load_candidate_from_dir(candidate_dir: str) -> dict:
    """Build a prompt_version-shaped dict from the working-tree Stage 3 files."""
    manifest = load_manifest(os.path.join(candidate_dir, "manifest.json"))
    entry = manifest[STAGE_3_LABEL]
    # Manifest paths are relative to the repo root, i.e. the parent of the prompts directory, and must
    # resolve inside the candidate directory: the manifest comes from the pull-request checkout.
    root = os.path.dirname(os.path.abspath(candidate_dir))
    files = {k: resolve_manifest_path(v, root, within=candidate_dir) for k, v in entry["files"].items() if v}
    data = read_prompt_files({"files": files})
    return {
        "id": f"working-tree:{candidate_dir}",
        "version": entry["version"],
        "description": entry.get("description", ""),
        **data,
    }


def describe_prompt(prompt_version: dict) -> str:
    return f"{prompt_version.get('id')} (v{prompt_version.get('version', '?')})"


def snippet_title(snippet: dict) -> str:
    title = snippet.get("title")
    if isinstance(title, dict):
        return title.get("english") or title.get("spanish") or ""
    return str(title or "")


async def evaluate_snippet(
    snippet_id: str,
    kind: str,
    data_source,
    runner,
    baseline_prompt: dict,
    candidate_prompt: dict,
    runs: int,
    workdir: str,
    semaphore: asyncio.Semaphore,
) -> SnippetResult:
    result = SnippetResult(snippet_id=snippet_id, kind=kind)
    try:
        snippet = data_source.fetch_snippet(snippet_id)
        if not snippet:
            result.error = "snippet not found"
            return result
        result.title = snippet_title(snippet)
        metadata = get_metadata(copy.deepcopy(snippet))
        audio_file = data_source.download_audio(snippet, workdir)
    except Exception as e:
        result.error = describe_exception(e, limit=300)
        return result

    async def guarded(prompt_version, side):
        async with semaphore:
            run_result = await runner.run(prompt_version, audio_file, metadata)
        if not run_result.ok:
            print(f"    run failed: {snippet_id} {side}: {run_result.error}", flush=True)
        return run_result

    try:
        baseline_and_candidate = await asyncio.gather(
            *[guarded(baseline_prompt, "baseline") for _ in range(runs)],
            *[guarded(candidate_prompt, "candidate") for _ in range(runs)],
        )
        result.baseline_runs = list(baseline_and_candidate[:runs])
        result.candidate_runs = list(baseline_and_candidate[runs:])
    finally:
        try:
            os.remove(audio_file)
        except OSError:
            pass
    return result


async def evaluate_snippets(
    selection: list[tuple[str, str]],
    data_source,
    runner,
    baseline_prompt: dict,
    candidate_prompt: dict,
    runs: int = DEFAULT_RUNS,
    threshold: int = DEFAULT_THRESHOLD,
    flag_on: str = "overall",
    concurrency: int = DEFAULT_CONCURRENCY,
    workdir: str | None = None,
) -> list[SnippetResult]:
    """Evaluate ``selection`` = [(snippet_id, kind), ...]; snippets run sequentially, model calls concurrently."""
    semaphore = asyncio.Semaphore(max(1, concurrency))
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        for index, (snippet_id, kind) in enumerate(selection, 1):
            print(f"[{index}/{len(selection)}] {kind} snippet {snippet_id}")
            result = await evaluate_snippet(
                snippet_id,
                kind,
                data_source,
                runner,
                baseline_prompt,
                candidate_prompt,
                runs,
                workdir or tmp,
                semaphore,
            )
            result.finalize(threshold, flag_on)
            print(f"    verdict: {result.verdict}" + (f" ({result.error})" if result.error else ""))
            results.append(result)
    return results


def results_to_json(results: list[SnippetResult], agg: dict, config: dict, notes: list[str]) -> dict:
    return {"config": config, "aggregate": agg, "notes": notes, "snippets": [asdict(r) for r in results]}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare a candidate Stage 3 prompt against the active one on real snippets (read-only).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    cand = parser.add_mutually_exclusive_group()
    cand.add_argument(
        "--candidate-dir",
        default="prompts",
        help="Prompt directory holding manifest.json; the stage_3 files there are the candidate (default: prompts)",
    )
    cand.add_argument("--candidate-version-id", help="prompt_versions.id to evaluate instead of working-tree files")
    parser.add_argument(
        "--baseline",
        default="active",
        help="'active' (default) for the active Stage 3 prompt_versions row, or a prompt_versions.id",
    )
    parser.add_argument("--baseline-version-id", help="Alias for --baseline <uuid>")

    sel = parser.add_argument_group("snippet selection")
    sel.add_argument("--snippet-ids", nargs="+", default=[], help="Snippet ids (treated as reported snippets)")
    sel.add_argument("--snippet-file", action="append", default=[], help="JSON list of ids or an eval-set file")
    sel.add_argument("--from-feedback", action="store_true", help="Snippets with a comment or dislike since --since")
    sel.add_argument("--since", help="YYYY-MM-DD; required with --from-feedback")
    sel.add_argument("--control", type=int, default=0, metavar="N", help="Add N random liked/never-disliked snippets")
    sel.add_argument("--control-days", type=int, default=90, help="Recording window for --control (default 90)")
    sel.add_argument("--seed", type=int, default=2026, help="RNG seed for --control (default 2026)")
    sel.add_argument("--max-snippets", type=int, help="Cap the number of snippets (reported first)")

    run = parser.add_argument_group("run settings")
    run.add_argument(
        "--runs", type=int, default=DEFAULT_RUNS, help=f"Runs per prompt per snippet (default {DEFAULT_RUNS})"
    )
    run.add_argument("--model", default=str(MAIN_MODEL), help=f"Gemini model for both prompts (default {MAIN_MODEL})")
    run.add_argument(
        "--threshold", type=int, default=DEFAULT_THRESHOLD, help=f"Flag threshold (default {DEFAULT_THRESHOLD})"
    )
    run.add_argument(
        "--flag-on", choices=FLAG_ON_CHOICES, default="overall", help="Score the flag uses (default overall)"
    )
    run.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Concurrent model calls per snippet (default {DEFAULT_CONCURRENCY})",
    )

    out = parser.add_argument_group("output")
    out.add_argument("--out", default="eval-report.md", help="Markdown report path (default eval-report.md)")
    out.add_argument("--json", dest="json_out", help="Also write full results as JSON")
    out.add_argument(
        "--fail-on-regression",
        nargs="?",
        const=0,
        type=int,
        metavar="N",
        help="Exit 1 if more than N control snippets lose their flag (default N=0 when given without a value)",
    )
    return parser


def build_selection(args, data_source, notes: list[str]) -> list[tuple[str, str]]:
    reported = list(args.snippet_ids)
    control = []
    for path in args.snippet_file:
        file_reported, file_control, description = load_snippet_file(path)
        reported += file_reported
        control += file_control
        notes.append(
            f"Eval set `{path}`: {description or 'no description'} "
            f"({len(file_reported)} reported, {len(file_control)} control)"
        )
    if args.from_feedback:
        if not args.since:
            raise SystemExit("--from-feedback requires --since YYYY-MM-DD")
        feedback_ids = data_source.feedback_snippet_ids(args.since)
        notes.append(f"{len(feedback_ids)} snippets with a comment or dislike since {args.since}")
        reported += feedback_ids
    if args.control:
        picked = pick_control(data_source.control_candidate_ids(args.control_days), args.control, args.seed)
        notes.append(f"{len(picked)} control snippets sampled with seed {args.seed} (last {args.control_days} days)")
        control += picked

    reported = dedupe(reported)
    reported_set = set(reported)
    control = [c for c in dedupe(control) if c not in reported_set]
    if args.max_snippets is not None:
        reported, control = cap_selection(reported, control, args.max_snippets)
    return [(i, REPORTED) for i in reported] + [(i, CONTROL) for i in control]


def cap_selection(reported: list, control: list, limit: int) -> tuple[list, list]:
    """Keep at most ``limit`` snippets, split evenly so a small run still has control snippets."""
    keep_reported = min(len(reported), max(limit - len(control), (limit + 1) // 2))
    return reported[:keep_reported], control[: limit - keep_reported]


def exit_code(agg: dict, fail_on_regression: int | None) -> int:
    if agg["runs_total"] and agg["runs_failed"] == agg["runs_total"]:
        print("Every model call failed; the report carries no evidence")
        return 1
    if fail_on_regression is not None and agg["true_positives_lost"] > fail_on_regression:
        print(f"Regression: {agg['true_positives_lost']} true positives lost (> {fail_on_regression})")
        return 1
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        print(f"Error: missing environment variables: {', '.join(missing)}", file=sys.stderr)
        return MISSING_ENV_EXIT_CODE
    if not os.getenv("SEARXNG_URL"):
        print("Warning: SEARXNG_URL is not set; the Stage 3 web search tool will fail inside the model calls.")

    started = time.monotonic()
    data_source = EvalDataSource.from_env()
    notes: list[str] = []

    baseline_ref = args.baseline_version_id or args.baseline
    baseline_prompt = (
        data_source.active_prompt() if baseline_ref == "active" else data_source.prompt_by_id(baseline_ref)
    )
    if args.candidate_version_id:
        candidate_prompt = data_source.prompt_by_id(args.candidate_version_id)
    else:
        candidate_prompt = load_candidate_from_dir(args.candidate_dir)

    selection = build_selection(args, data_source, notes)
    if not selection:
        print("Error: no snippets selected", file=sys.stderr)
        return 1

    print(f"Baseline: {describe_prompt(baseline_prompt)}")
    print(f"Candidate: {describe_prompt(candidate_prompt)}")
    print(f"Evaluating {len(selection)} snippets x {args.runs} runs x 2 prompts on {args.model}")

    runner = GeminiRunner.from_env(args.model)
    results = asyncio.run(
        evaluate_snippets(
            selection,
            data_source,
            runner,
            baseline_prompt,
            candidate_prompt,
            runs=args.runs,
            threshold=args.threshold,
            flag_on=args.flag_on,
            concurrency=args.concurrency,
        )
    )

    agg = aggregate(results, args.model)
    config = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "baseline": describe_prompt(baseline_prompt),
        "candidate": describe_prompt(candidate_prompt),
        "model": args.model,
        "runs": args.runs,
        "threshold": args.threshold,
        "flag_on": args.flag_on,
        "wall_seconds": time.monotonic() - started,
    }
    for r in results:
        if r.error:
            notes.append(f"`{r.snippet_id}` skipped: {r.error}")

    report = render_report(results, agg, config, notes)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report written to {args.out}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(results_to_json(results, agg, config, notes), f, indent=2, default=str)
        print(f"Results written to {args.json_out}")

    print(
        f"False positives fixed: {agg['false_positives_fixed']}/{agg['reported_total']} | "
        f"True positives lost: {agg['true_positives_lost']}/{agg['control_total']}"
    )
    return exit_code(agg, args.fail_on_regression)


if __name__ == "__main__":
    sys.exit(main())
