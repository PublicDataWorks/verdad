"""Stage 3 (in-depth analysis) eval on candidate models, using the repo's Stage3Executor as-is.

Runs the production Stage 3 prompt + tool loop (SearXNG web search) on real snippet clips and compares the
structured output across models. Reference = production output stored on the snippet (gemini-2.5-pro mostly),
plus human labels. A 2.5 Pro rerun measures run-to-run noise.

Requires: REPO (default: this repo's root, checked out on the migration branch so 3.x thinking works),
PYTHONPATH handled here, ENABLE_PREFECT_DECORATOR=false, SEARXNG_URL, GOOGLE_GEMINI_KEY from the eval key file.

Usage: python stage3_eval.py run --model gemini-3.8-flash [--tag r2] [--limit N] [--ids a,b] [--workers 3]
       python stage3_eval.py report
"""

import argparse
import asyncio
import contextvars
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO", HERE.parents[2]))  # repo root: docs/migration-2026-11/eval -> ../../..
os.environ.setdefault("ENABLE_PREFECT_DECORATOR", "false")
os.environ.setdefault("SEARXNG_URL", "https://verdad-searxng.fly.dev")
if not os.environ.get("GOOGLE_GEMINI_KEY"):
    sys.exit("set GOOGLE_GEMINI_KEY to a Gemini API key (paid tier for 3.x models)")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO))
os.chdir(REPO)  # prompts/ relative paths inside the repo

from cost_model import usage_cost  # noqa: E402
from google import genai  # noqa: E402
from google.genai.types import HttpOptions  # noqa: E402

from processing_pipeline.stage_3.executors import Stage3Executor  # noqa: E402

RESULTS = HERE / "results_stage3"
PRICE = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-pro-preview": (2.0, 12.0),
}
_tally = contextvars.ContextVar("tally")


def count_analysis_usage(client):
    """Tally implicit-cache hits and tool-loop turns per analysis: the executor's usage dict has neither."""
    generate = client.aio.models.generate_content

    async def counted(**kwargs):
        response = await generate(**kwargs)
        tally = _tally.get(None)
        if tally is not None and kwargs["config"].response_schema is None:
            tally[1] += 1
            if response.usage_metadata:
                tally[0] += response.usage_metadata.cached_content_token_count or 0
        return response

    client.aio.models.generate_content = counted


def prompt_version():
    p = REPO / "prompts" / "stage_3"
    return {
        "system_instruction": (p / "system_instruction.md").read_text(),
        "user_prompt": (p / "analysis_prompt.md").read_text(),
        "output_schema": json.load(open(p / "output_schema.json")),
    }


def build_metadata(sel, data, snip):
    """Mirror processing_pipeline.stage_3.tasks.__get_metadata."""
    flagged = next((f for f in (data["stage_1"]["flagged_snippets"] or []) if f.get("uuid") == sel["snippet_id"]), None)
    md = (
        dict(flagged)
        if flagged
        else {
            "uuid": sel["snippet_id"],
            "transcription": snip.get("transcription") or "",
            "disinformation_categories": snip.get("disinformation_categories") or [],
            "keywords_detected": [],
            "explanation": "",
        }
    )
    af = dict(data["audio_file"])
    # snippets.recorded_at was not pulled into the dataset; reconstruct it as the production Stage 2 does:
    # audio_file.recorded_at + clip start (flagged start minus the 90 s context, clamped at 0).
    base = datetime.fromisoformat(data["audio_file"]["recorded_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    clip_start = 0
    if flagged and flagged.get("start_time"):
        mm, ss = flagged["start_time"].split(":")[-2:]
        clip_start = max(0, int(mm) * 60 + int(ss) - 90)
    rec = base + timedelta(seconds=clip_start)
    af["recorded_at"] = rec.strftime("%B %-d, %Y %-I:%M %p")
    af["recorded_at_iso"] = rec.isoformat()
    af["recording_day_of_week"] = rec.strftime("%A")
    af["time_zone"] = "UTC"
    for k in ("id", "file_path", "file_size"):
        af.pop(k, None)
    md["additional_info"] = af
    for k in ("start_time", "end_time", "explanation", "keywords_detected"):
        md.pop(k, None)
    md["start_time"] = snip["start_time"].split(":", 1)[1]
    md["end_time"] = snip["end_time"].split(":", 1)[1]
    md["duration"] = snip["duration"].split(":", 1)[1]
    return md


async def run_one(client, model, pv, sel, data, snip, outp):
    md = build_metadata(sel, data, snip)
    tally = [0, 0]
    _tally.set(tally)
    t = time.time()
    try:
        res = await Stage3Executor.run_async(
            gemini_client=client,
            model_name=model,
            audio_file=str(HERE / "snippets" / f"{sel['snippet_id']}.mp3"),
            metadata=md,
            prompt_version=pv,
        )
        r = res["response"]
        u = {**(res.get("usage") or {}), "cached_content_token_count": tally[0]}
        cost = usage_cost(u, *PRICE.get(model, (0, 0)))
        out = {
            "ok": True,
            "snippet_id": sel["snippet_id"],
            "model": model,
            "latency": round(time.time() - t, 1),
            "turns": tally[1],
            "usage": u,
            "cost_usd": round(cost, 4),
            "overall": (r.get("confidence_scores") or {}).get("overall"),
            "categories": r.get("disinformation_categories"),
            "title": (r.get("title") or {}).get("english"),
            "political_leaning": r.get("political_leaning"),
            "skip_review": r.get("skip_review"),
            "grounding": json.loads(res.get("grounding_metadata") or "{}"),
            "response": r,
        }
    except Exception as e:
        out = {
            "ok": False,
            "snippet_id": sel["snippet_id"],
            "model": model,
            "latency": round(time.time() - t, 1),
            "error": f"{type(e).__name__}: {str(e)[:400]}",
        }
    json.dump(out, open(outp, "w"), ensure_ascii=False, indent=1, default=str)
    return out


def fetch_clips(selection):
    """Clips stay in R2, like the recordings (fetch_audio.py); snippets/ is git-ignored."""
    (HERE / "snippets").mkdir(exist_ok=True)
    for sel in selection:
        dst = HERE / "snippets" / f"{sel['snippet_id']}.mp3"
        if not dst.exists():
            req = urllib.request.Request(
                "https://audio.verdad.app/" + sel["file_path"], headers={"User-Agent": "verdad-eval"}
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                dst.write_bytes(resp.read())


async def run(model, tag, selection, workers):
    fetch_clips(selection)
    # Same as GEMINI_HTTP_OPTIONS (VER-456), inlined so REPO checkouts without it still run.
    client = genai.Client(api_key=os.environ["GOOGLE_GEMINI_KEY"], http_options=HttpOptions(timeout=600_000))
    count_analysis_usage(client)
    pv = prompt_version()
    outdir = RESULTS / (f"{model}-{tag}" if tag else model)
    outdir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(workers)

    async def guarded(sel):
        outp = outdir / f"{sel['snippet_id']}.json"
        if outp.exists():
            return sel["snippet_id"], "cached"
        data = json.load(open(HERE / "data" / f"{sel['audio_file_id']}.json"))
        snip = next(s for s in data["snippets"] if s["id"] == sel["snippet_id"])
        async with sem:
            out = await run_one(client, model, pv, sel, data, snip, outp)
        return sel["snippet_id"], (
            f"overall={out['overall']} cats={len(out['categories'] or [])} turns={out['turns']} tools={(out['grounding'].get('tool_usage') or {})} {out['latency']}s ${out['cost_usd']}"
            if out["ok"]
            else f"FAILED {out['error'][:200]}"
        )

    for coro in asyncio.as_completed([guarded(s) for s in selection]):
        sid, msg = await coro
        print(model, sid[:8], msg, flush=True)


def report(selection):
    models = sorted(p.name for p in RESULTS.iterdir() if p.is_dir())
    bysel = {s["snippet_id"]: s for s in selection}
    print(
        f"{'model':24s} {'n':>3s} {'fail':>4s} {'mean overall':>12s} {'ref overall':>11s} {'|d| overall':>11s} {'>=95 agree':>10s} {'cat jaccard':>11s} {'human-flag':>10s} {'$/snip':>7s} {'s/snip':>6s} {'turns':>5s}"
    )
    for model in models:
        n = fail = 0
        so = sr = sd = 0.0
        agree = 0
        jac = 0.0
        hum = hum_hit = 0
        cost = lat = turns = 0.0
        for p in (RESULTS / model).glob("*.json"):
            r = json.load(open(p))
            s = bysel.get(r["snippet_id"])
            if not s:
                continue
            if not r.get("ok"):
                fail += 1
                continue
            n += 1
            o = r.get("overall") or 0
            ref = s.get("overall") or 0
            so += o
            sr += ref
            sd += abs(o - ref)
            agree += int((o >= 95) == (ref >= 95))
            cost += r.get("cost_usd") or 0
            lat += r["latency"]
            turns += r.get("turns") or 0
            norm = lambda xs: {json.dumps(x, sort_keys=True) if isinstance(x, dict) else str(x) for x in (xs or [])}  # noqa: E731
            a = norm(r.get("categories"))
            b = norm(s.get("categories"))
            jac += (len(a & b) / len(a | b)) if (a | b) else 1.0
            if s["human_labels"]:
                hum += 1
                hum_hit += int(o >= 80)
        if n:
            print(
                f"{model:24s} {n:3d} {fail:4d} {so / n:12.1f} {sr / n:11.1f} {sd / n:11.1f} {agree / n:10.2f} {jac / n:11.2f} {f'{hum_hit}/{hum}':>10s} {cost / n:7.3f} {lat / n:6.0f} {turns / n:5.1f}"
            )
        else:
            print(f"{model:24s} no ok results; fail={fail}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--tag", help="repeat-run suffix for the results directory, e.g. r2")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    selection = json.load(open(HERE / "snippets_selection.json"))
    if a.ids:
        w = a.ids.split(",")
        selection = [s for s in selection if s["snippet_id"] in w or s["snippet_id"][:8] in w]
    if a.limit:
        selection = selection[: a.limit]
    if a.cmd == "run":
        asyncio.run(run(a.model, a.tag, selection, a.workers))
    else:
        report(selection)
