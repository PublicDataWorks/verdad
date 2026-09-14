#!/usr/bin/env python3
"""Run one pipeline stage locally as plain Python, without a Prefect server.

Sets ENABLE_PREFECT_DECORATOR=false before importing anything from src/, so the
@optional_flow/@optional_task decorators are no-ops and the flow functions in
src/processing_pipeline/stage_N/flows.py run as ordinary (async) functions.

Everything else is real: the stage talks to the Supabase project, R2 bucket and
LLM providers configured in .env (loaded from the repo root if present). Point
.env at a non-production project before running this against anything.

Examples:
    python scripts/run_stage.py --stage 1 --audio-file-id <uuid>
    python scripts/run_stage.py --stage 1 --limit 3            # next 3 "New" audio files
    python scripts/run_stage.py --stage 2                      # clip the next "New" stage-1 response
    python scripts/run_stage.py --stage 3 --snippet-id <uuid> [--snippet-id <uuid>] [--skip-review]
    python scripts/run_stage.py --stage 4 --snippet-id <uuid>
    python scripts/run_stage.py --stage 5                      # embed the next snippet without one
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Must happen before any `processing_pipeline` import: the decorators read this at import time.
os.environ["ENABLE_PREFECT_DECORATOR"] = "false"

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is in requirements.txt
    load_dotenv = None


def run_stage_1(args):
    from processing_pipeline.stage_1 import initial_disinformation_detection

    # With --audio-file-id the flow processes that file and returns; otherwise it takes
    # the next "New" audio files until `limit` are done (sleeping 60s when the queue is empty).
    initial_disinformation_detection(audio_file_id=args.audio_file_id, limit=args.limit)


def run_stage_2(args):
    from processing_pipeline.stage_2 import audio_clipping

    # Stage 2 has no per-id entrypoint; repeat=False processes the next "New" stage-1 response once.
    audio_clipping(
        context_before_seconds=args.context_before_seconds,
        context_after_seconds=args.context_after_seconds,
        repeat=False,
    )


def run_stage_3(args):
    from processing_pipeline.stage_3 import in_depth_analysis

    asyncio.run(in_depth_analysis(snippet_ids=args.snippet_ids, skip_review=args.skip_review, repeat=False))


def run_stage_4(args):
    from processing_pipeline.stage_4 import analysis_review

    asyncio.run(analysis_review(snippet_ids=args.snippet_ids, repeat=False))


def run_stage_5(args):
    from processing_pipeline.stage_5 import embedding

    embedding(repeat=False)


STAGE_RUNNERS = {1: run_stage_1, 2: run_stage_2, 3: run_stage_3, 4: run_stage_4, 5: run_stage_5}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", type=int, choices=sorted(STAGE_RUNNERS), required=True)
    parser.add_argument("--audio-file-id", help="stage 1: process this audio_files.id only")
    parser.add_argument("--limit", type=int, default=1, help="stage 1: number of new audio files to process (default 1)")
    parser.add_argument(
        "--snippet-id", dest="snippet_ids", action="append", default=[], help="stage 3/4: snippets.id (repeatable)"
    )
    parser.add_argument("--skip-review", action="store_true", help="stage 3: mark snippets Processed instead of Ready for review")
    parser.add_argument("--context-before-seconds", type=int, default=90, help="stage 2 (default 90)")
    parser.add_argument("--context-after-seconds", type=int, default=60, help="stage 2 (default 60)")
    parser.add_argument("--env-file", default=str(REPO_ROOT / ".env"), help="dotenv file to load (default: <repo>/.env)")
    return parser


def parse_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.stage != 1 and (args.audio_file_id or args.limit != 1):
        parser.error("--audio-file-id/--limit only apply to --stage 1")
    if args.stage not in (3, 4) and args.snippet_ids:
        parser.error("--snippet-id only applies to --stage 3 or 4")
    if args.stage != 3 and args.skip_review:
        parser.error("--skip-review only applies to --stage 3")
    return args


def main(argv=None):
    args = parse_args(argv)
    if load_dotenv is not None and os.path.exists(args.env_file):
        load_dotenv(args.env_file)
    print(f"Running stage {args.stage} locally (ENABLE_PREFECT_DECORATOR=false)")
    STAGE_RUNNERS[args.stage](args)


if __name__ == "__main__":
    main()
