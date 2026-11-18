"""Daily production cost model from measured eval usage.

Volumes (from production, Oct 2026): RECORDINGS/day full 30-min files through Stage 1; TS_SHARE of them pass the
initial-detection gate and get the timestamped transcription + main detection; SNIPPETS/day reach Stage 3.
"""

import glob
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECORDINGS = 2400
TS_SHARE = float((HERE / "ts_share.txt").read_text()) if (HERE / "ts_share.txt").exists() else 0.39
SNIPPETS = 1020
PRICE = {  # $/1M input (audio rate where it differs), output
    "gemini-2.5-flash": (1.00, 2.50),
    "gemini-2.5-flash-text": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemma-4-26b-a4b-it-maas": (0.0, 0.0),
    "gemma-4-31b-it": (0.0, 0.0),
}
# The pricing page (4 Nov 2026) bills cached input at 10% of the input rate on every model it lists.
CACHED_RATE = 0.10


def usage_cost(u, pin, pout):
    """Cost of one analysis from its token usage, cached input at CACHED_RATE."""
    cached = u.get("cached_content_token_count") or 0
    return (
        ((u.get("prompt_token_count") or 0) - cached + cached * CACHED_RATE) * pin
        + ((u.get("candidates_token_count") or 0) + (u.get("thoughts_token_count") or 0)) * pout
    ) / 1e6


def mean_cost(dirpath, key="cost_usd"):
    vals = [json.load(open(p)).get(key) for p in glob.glob(str(dirpath / "*.json"))]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return (st.mean(vals), len(vals)) if vals else (None, 0)


def main():
    print("Measured per-unit costs (mean over eval files)")
    tr = {}
    for d in sorted((HERE / "results").glob("*")):
        if d.is_dir():
            c, n = mean_cost(d)
            tr[d.name] = c
            print(
                f"  timestamped transcription  {d.name:28s} ${c:.4f}/file  (n={n})"
                if c is not None
                else f"  {d.name}: no data"
            )
    det = {}
    for d in sorted((HERE / "results_detection").glob("*")):
        if d.is_dir():
            c, n = mean_cost(d)
            det[d.name] = c
            print(
                f"  main detection             {d.name:28s} ${c:.4f}/file  (n={n})"
                if c is not None
                else f"  {d.name}: no data"
            )
    s3 = {}
    for d in sorted((HERE / "results_stage3").glob("*")):
        if d.is_dir():
            rows = [json.load(open(p)) for p in glob.glob(str(d / "*.json"))]
            rows = [r for r in rows if r.get("ok") and r.get("usage")]
            if not rows:
                print(f"  stage 3 analysis           {d.name:28s} no data")
                continue
            c = st.mean(usage_cost(r["usage"], *PRICE.get(d.name, (0, 0))) for r in rows)
            s3[d.name] = c
            print(f"  stage 3 analysis           {d.name:28s} ${c:.4f}/snippet (n={len(rows)}, mean prompt tokens {int(st.mean(r['usage'].get('prompt_token_count') or 0 for r in rows)):,})")
    # Stage 1 initial transcription (whole file, Files API) is priced from audio tokens: 30 min * 32 tok/s = 57.6k tokens
    audio_tokens = 1800 * 32
    init_tx = {
        m: audio_tokens / 1e6 * PRICE[m][0] + 6000 / 1e6 * PRICE[m][1]
        for m in ("gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash")
    }
    # initial detection: text only, about 12k in / 1k out
    init_det = {
        m: 12000 / 1e6 * PRICE[m][0] + 1500 / 1e6 * PRICE[m][1]
        for m in ("gemini-2.5-flash-text", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemma-4-26b-a4b-it-maas")
    }
    print(
        f"\nVolumes: {RECORDINGS} recordings/day, {TS_SHARE:.0%} reach timestamped transcription, {SNIPPETS} snippets/day to Stage 3\n"
    )
    scenarios = {
        "A. today (2.5 Flash + 2.5 Pro), list price": dict(
            init="gemini-2.5-flash",
            idet="gemini-2.5-flash-text",
            ts="gemini-2.5-flash",
            det="gemini-2.5-flash",
            s3="gemini-2.5-pro",
        ),
        "B. all 3.5 Flash Lite, segment transcription": dict(
            init="gemini-3.5-flash-lite",
            idet="gemini-3.5-flash-lite",
            ts="gemini-3.5-flash-lite",
            det="gemini-3.5-flash-lite",
            s3="gemini-3.5-flash-lite",
        ),
        "C. 3.5 Transcribe for timestamps, Flash Lite elsewhere, 3.8 Flash for Stage 3": dict(
            init="gemini-3.5-flash-lite",
            idet="gemini-3.5-flash-lite",
            ts="gemini-3.5-transcribe",
            det="gemini-3.5-flash-lite",
            s3="gemini-3.8-flash",
        ),
        "D. C but Gemma 4 (free) for both detection passes": dict(
            init="gemini-3.5-flash-lite",
            idet="gemma-4-26b-a4b-it-maas",
            ts="gemini-3.5-transcribe",
            det="gemma-4-26b-a4b-it-maas",
            s3="gemini-3.8-flash",
        ),
        "E. D but Stage 3 on 3.5 Flash Lite": dict(
            init="gemini-3.5-flash-lite",
            idet="gemma-4-26b-a4b-it-maas",
            ts="gemini-3.5-transcribe",
            det="gemma-4-26b-a4b-it-maas",
            s3="gemini-3.5-flash-lite",
        ),
    }
    for name, sc in scenarios.items():
        ts_cost = tr.get(sc["ts"]) if sc["ts"] != "gemini-2.5-flash" else 1800 * 32 / 1e6 * 1.00 + 8000 / 1e6 * 2.5
        det_cost = det.get(sc["det"]) if sc["det"] != "gemini-2.5-flash" else det.get("gemini-2.5-flash")
        s3_cost = s3.get(sc["s3"])
        if (
            s3_cost is None and s3.get("gemini-2.5-pro") is not None
        ):  # scale the measured 2.5 Pro token usage to the other model's prices
            base = [json.load(open(p)) for p in glob.glob(str(HERE / "results_stage3" / "gemini-2.5-pro" / "*.json"))]
            base = [b for b in base if b.get("ok")]
            pin, pout = PRICE[sc["s3"]]
            s3_cost = st.mean(usage_cost(b["usage"], pin, pout) for b in base)
            s3_note = " (scaled from 2.5 Pro token usage)"
        else:
            s3_note = ""
        if None in (ts_cost, det_cost, s3_cost):
            print(f"{name}: missing data ({sc})")
            continue
        stage1 = RECORDINGS * (init_tx[sc["init"]] + init_det[sc["idet"]]) + RECORDINGS * TS_SHARE * (
            ts_cost + det_cost
        )
        stage3 = SNIPPETS * s3_cost
        print(
            f"{name}\n   Stage 1 ${stage1:,.0f}/day  (initial tx+det ${RECORDINGS * (init_tx[sc['init']] + init_det[sc['idet']]):,.0f}, timestamps+main det ${RECORDINGS * TS_SHARE * (ts_cost + det_cost):,.0f})   Stage 3 ${stage3:,.0f}/day{s3_note}   total ${stage1 + stage3:,.0f}/day, ${(stage1 + stage3) * 30:,.0f}/month\n"
        )


if __name__ == "__main__":
    main()
