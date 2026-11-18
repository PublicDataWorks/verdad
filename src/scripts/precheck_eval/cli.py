"""Command line for the decision-model pre-check evaluation (VER-475). Eval only; production is untouched.

    PYTHONPATH=.:src python -m src.scripts.precheck_eval run --provider cloudflare --model clef \\
        --variant full --dataset precheck.jsonl --split dev --max-calls 50 [--dry-run]
    PYTHONPATH=.:src python -m src.scripts.precheck_eval report --dataset precheck.jsonl
    PYTHONPATH=.:src python -m src.scripts.precheck_eval synth --out synthetic.jsonl --n 200

``run`` calls one provider for each selected clip and appends every result to the cache; clips already
cached are not called again. ``report`` scores everything in the cache against the dataset, with no
network. Keys: TYPESAFE_API_KEY, CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN, PARALLEL_API_KEY,
OPENROUTER_API_KEY; ``parallel_mcp`` needs none; ``jev_compatible`` reads DECISION_BASE_URL (and an optional
DECISION_API_KEY).
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .cache import ResponseCache
from .config import (
    BOOTSTRAP_SAMPLES,
    BOOTSTRAP_SEED,
    CLIPS_PER_DAY,
    DEFAULT_OUTPUT_DIR,
    MAX_STATE_TOKENS,
    PROVIDERS,
    STAGE3_COST_PER_CLIP,
)
from .dataset import load_dataset, read_ids_file, select_clips
from .evaluate import TEXT_EPOCHS, EvalOptions
from .providers import make_client, missing_env
from .report import build_report, render_markdown
from .runner import dry_run_text, pending, prepare, run_calls, run_variant
from .synthetic import write_dataset
from .variants import QUESTION_SETS, STATE_VARIANTS, questions_for

MISSING_ENV_EXIT_CODE = 2
RATE_LIMITED_EXIT_CODE = 3


def non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative integer, got {number}")
    return number


def stage3_cost(value: str) -> tuple[str, float]:
    """argparse type for ``model=dollars``."""
    name, sep, dollars = value.partition("=")
    try:
        if not sep or not name:
            raise ValueError
        return name, float(dollars)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected MODEL=DOLLARS, got {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.scripts.precheck_eval",
        description="Evaluate decision models as a cheap pre-check before Stage 3 (VER-475).",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_OUTPUT_DIR / "cache"),
        help=f"Response cache (default {DEFAULT_OUTPUT_DIR}/cache; PRECHECK_EVAL_DIR moves the root)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Call one provider for the selected clips (cached, resumable)")
    run.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    run.add_argument("--model", help="Model id (default: the provider's default in config.py)")
    run.add_argument("--variant", choices=sorted(STATE_VARIANTS), help="State variant (default per provider)")
    run.add_argument("--questions", choices=sorted(QUESTION_SETS), help="Question set (default per provider)")
    run.add_argument("--dataset", required=True, help="Dataset JSONL")
    run.add_argument("--split", choices=("dev", "test", "all"), default="all")
    run.add_argument("--ids-file", help="Only these snippet ids (JSON list or one per line)")
    run.add_argument("--limit", type=non_negative_int, help="At most this many clips (after --split/--ids-file)")
    run.add_argument("--max-calls", type=non_negative_int, help="Hard budget of vendor calls for this run")
    run.add_argument("--concurrency", type=int, help="Calls in flight (default per provider)")
    run.add_argument("--rpm", type=float, help="Requests per minute (default per provider)")
    run.add_argument(
        "--repeats", type=int, default=1, help="Calls per clip; scorers use the mean, the report shows the spread"
    )
    run.add_argument(
        "--no-shuffle-choices", action="store_true", help="Keep choice options in a fixed order (default: per-clip shuffle)"
    )
    run.add_argument(
        "--max-state-tokens",
        type=int,
        default=MAX_STATE_TOKENS,
        help=f"State budget in estimated tokens (default {MAX_STATE_TOKENS}; a different value is a separate run)",
    )
    run.add_argument("--retry-errors", action="store_true", help="Call again for clips whose cached call failed")
    run.add_argument("--dry-run", action="store_true", help="Print one request and the estimated calls and cost")

    rep = sub.add_parser("report", help="Score every cached run against the dataset (no network)")
    rep.add_argument("--dataset", required=True)
    rep.add_argument("--out", help="Markdown path (default <cache-dir>/../report.md)")
    rep.add_argument("--json", dest="json_out", help="JSON path (default <cache-dir>/../report.json)")
    rep.add_argument("--runs", nargs="+", help="Only these run ids (provider/model/variant.questions)")
    rep.add_argument("--common-clips", action="store_true", help="Score every run on the clips all runs share")
    rep.add_argument("--no-baselines", action="store_true")
    rep.add_argument("--bootstrap", type=non_negative_int, default=BOOTSTRAP_SAMPLES)
    rep.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    rep.add_argument("--label-field", default="stage3_overall", help="label.<field> used as the answer key")
    rep.add_argument(
        "--stage3-cost",
        type=stage3_cost,
        action="append",
        metavar="MODEL=DOLLARS",
        help="Stage 3 cost per clip; repeatable (default "
        + ", ".join(f"{k}={v}" for k, v in STAGE3_COST_PER_CLIP.items())
        + ")",
    )
    rep.add_argument("--clips-per-day", type=float, default=CLIPS_PER_DAY)
    rep.add_argument(
        "--text-epochs", type=int, default=TEXT_EPOCHS, help=f"Epochs for the text_lr baseline (default {TEXT_EPOCHS})"
    )

    syn = sub.add_parser("synth", help="Write a seeded synthetic dataset in the real schema")
    syn.add_argument("--out", required=True)
    syn.add_argument("--n", type=non_negative_int, default=200)
    syn.add_argument("--seed", type=int, default=475)
    return parser


def cmd_run(args, env=None, transport=None, log=print) -> int:
    spec = PROVIDERS[args.provider]
    model = args.model or spec.default_model
    state_variant = args.variant or spec.default_variant
    question_set = args.questions or spec.default_questions
    if spec.web_grounded and "station" in STATE_VARIANTS[state_variant]:
        log("Note: VER-443 found station metadata steers Parallel's retrieval; the 'claim' variant avoids it.")
    clips, problems = load_dataset(args.dataset)
    for p in problems:
        log(f"dataset: {p}")
    ids = read_ids_file(args.ids_file) if args.ids_file else None
    clips = select_clips(clips, args.split, ids, args.limit)
    if not clips:
        log("Error: no clips selected")
        return 1
    try:
        client = make_client(args.provider, model, env=env, transport=transport, rpm=args.rpm)
    except ValueError as exc:
        log(f"Error: {exc}")
        return 1
    questions = questions_for(question_set)
    client.validate(questions)
    prepared = prepare(
        clips, client, state_variant, question_set, questions, repeats=args.repeats,
        shuffle=not args.no_shuffle_choices, max_state_tokens=args.max_state_tokens,
    )
    cache = ResponseCache(args.cache_dir)
    variant = run_variant(state_variant, question_set, args.max_state_tokens)
    if args.dry_run:
        todo = pending(prepared, cache.load(spec.name, model, variant), args.retry_errors)
        log(dry_run_text(client, prepared, todo))
        if args.max_calls is not None:
            log(f"--max-calls {args.max_calls} would stop the run after {min(args.max_calls, len(todo))} calls")
        return 0
    missing = missing_env(args.provider, env)
    if missing:
        log(f"Error: missing environment variables: {', '.join(missing)}")
        return MISSING_ENV_EXIT_CODE
    log(f"Run {spec.name}/{model}/{variant} on {len(prepared)} clips; cache {cache.path_for(spec.name, model, variant)}")
    summary = asyncio.run(
        run_calls(
            client, prepared, cache, state_variant, question_set, questions,
            concurrency=args.concurrency, max_calls=args.max_calls, retry_errors=args.retry_errors,
            max_state_tokens=args.max_state_tokens, log=log,
        )
    )
    log(json.dumps(summary))
    if summary["rate_limited"]:
        return RATE_LIMITED_EXIT_CODE
    if summary["calls"] and summary["errors"] == summary["calls"]:
        log("Every call failed; check the key and the error above")
        return 1
    return 0


def cmd_report(args, log=print) -> int:
    clips, problems = load_dataset(args.dataset)
    records = ResponseCache(args.cache_dir).all_records()
    opts = EvalOptions(label_field=args.label_field, bootstrap=args.bootstrap, seed=args.seed)
    stage3_costs = dict(args.stage3_cost) if args.stage3_cost else None
    report = build_report(
        clips, records, opts, stage3_costs=stage3_costs, clips_per_day=args.clips_per_day, run_filter=args.runs,
        common_clips=args.common_clips, with_baselines=not args.no_baselines, text_epochs=args.text_epochs,
        problems=[f"dataset: {p}" for p in problems],
    )
    root = Path(args.cache_dir).parent
    out = Path(args.out or root / "report.md")
    json_out = Path(args.json_out or root / "report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(report), encoding="utf-8")
    json_out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    log(f"{len(report['runs'])} runs, {len(report['baselines'])} baselines. Report: {out} JSON: {json_out}")
    return 0


def main(argv=None, env=None, transport=None, log=print) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args, env=env, transport=transport, log=log)
    if args.command == "report":
        return cmd_report(args, log=log)
    count = write_dataset(args.out, args.n, args.seed)
    log(f"Wrote {count} synthetic clips to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
