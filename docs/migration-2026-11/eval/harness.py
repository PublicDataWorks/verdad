"""Transcription eval harness for the VERDAD Gemini 2.5 exit.

Two approaches, same output format (one text per 20 s window, as production writes "[MM:SS] text"):
  A. segments   : cut the 30-min mp3 into 20 s clips, send 30 clips per request with the production Stage 1
                  timestamped-transcription prompts (what the pipeline does today), on a candidate model.
  B. transcribe : one gemini-3.5-transcribe request per file (REST interactions API, word timestamps), words
                  bucketed into the same 20 s windows by start_offset.

Reference = the production gemini-2.5-flash segment transcript stored in stage_1_llm_responses. It is not ground
truth, so we also report pairwise agreement between candidates and an alignment-shift test for B.

Usage:
  python harness.py segments --model gemini-3.5-flash-lite [--ids a,b] [--limit N] [--workers 4]
  python harness.py transcribe [--ids a,b] [--limit N] [--variant lang|diar|lang+diar]
  python harness.py report
"""

import argparse
import json
import re
import subprocess
import time
import unicodedata
import concurrent.futures as cf
import os
import sys
from pathlib import Path

import requests
from rapidfuzz import fuzz
from google import genai
from google.genai import types, errors

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("REPO", HERE.parents[2]))  # repo root
KEY = os.environ.get("GOOGLE_GEMINI_KEY") or sys.exit("set GOOGLE_GEMINI_KEY to a Gemini API key")
RESULTS = HERE / "results"
SEG_LEN = 20
BATCH = 30

# $ per 1M tokens (Gemini API list, 2026-10-30). transcribe is per-minute: $0.003 in, $0.002 out.
PRICE = {
    "gemini-2.5-flash": (1.00, 2.50),  # audio input rate
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (0.30, 2.50),  # not on pricing page; assume Flash-Lite rate (flag in report)
    "gemini-3.6-flash": (0.75, 3.75),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-flash-lite": (0.50, 1.50),
}


def norm(s: str) -> str:
    s = re.sub(r"\[[^\]]*\]", " ", s or "")  # drop [music], [inaudible] tags
    s = unicodedata.normalize("NFKC", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_ts_transcript(text: str) -> dict[int, str]:
    """'[MM:SS] text' lines -> {start_seconds: text}."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r"\[(\d+):(\d\d)\]\s?(.*)", line)
        if m:
            out[int(m.group(1)) * 60 + int(m.group(2))] = m.group(3)
    return out


def windows_from_words(words: list[dict], seg_len=SEG_LEN) -> dict[int, str]:
    out: dict[int, list[str]] = {}
    for w in words:
        t = w["start"]
        k = int(t // seg_len) * seg_len
        out.setdefault(k, []).append(w["text"])
    return {k: " ".join(v) for k, v in out.items()}


def window_scores(ref: dict[int, str], cand: dict[int, str], shift=0) -> dict:
    keys = sorted(ref)
    sims, nonempty = [], 0
    for k in keys:
        r = norm(ref[k])
        c = norm(cand.get(k + shift, ""))
        if not r and not c:
            continue
        nonempty += 1
        sims.append(fuzz.token_set_ratio(r, c) if (r and c) else 0.0)
    if not sims:
        return {"mean": None, "p_ge70": None, "n": 0}
    return {
        "mean": round(sum(sims) / len(sims), 1),
        "p_ge70": round(sum(1 for s in sims if s >= 70) / len(sims), 3),
        "n": len(sims),
    }


def wer(ref: str, hyp: str) -> float | None:
    try:
        import jiwer

        r, h = norm(ref), norm(hyp)
        if not r:
            return None
        return round(jiwer.wer(r, h), 3)
    except Exception:
        return None


def load_manifest(ids=None, limit=None):
    man = json.load(open(HERE / "data" / "manifest.json"))
    if ids:
        want = set(ids)
        man = [m for m in man if m["audio_file_id"] in want or m["audio_file_id"][:8] in want]
    if limit:
        man = man[:limit]
    return man


def load_data(aid):
    return json.load(open(HERE / "data" / f"{aid}.json"))


def prompts():
    p = REPO / "prompts" / "stage_1" / "main"
    return {
        "system_instruction": (p / "timestamped_transcription_system_instruction.md").read_text(),
        "user_prompt": (p / "timestamped_transcription_user_prompt.md").read_text(),
        "output_schema": json.load(open(p / "timestamped_transcription_output_schema.json")),
    }


# ---------------------------------------------------------------- A. segments (production approach)
def split_segments(aid: str, mp3: Path) -> list[Path]:
    d = HERE / "segments" / aid
    d.mkdir(parents=True, exist_ok=True)
    dur = float(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)]
        )
        .decode()
        .strip()
    )
    n = int(-(-dur // SEG_LEN))
    if n * SEG_LEN - dur > SEG_LEN - 1.0:  # trailing sliver under 1 s (mp3 duration rounding): skip it
        n -= 1
    paths = []
    for i in range(n):
        out = d / f"seg_{i + 1:03d}.mp3"
        if not out.exists() or out.stat().st_size == 0:
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-ss",
                    str(i * SEG_LEN),
                    "-t",
                    str(SEG_LEN),
                    "-i",
                    str(mp3),
                    "-ac",
                    "1",
                    "-b:a",
                    "64k",
                    str(out),
                ],
                check=True,
            )
        paths.append(out)
    return paths


def gen_config(model: str, pv: dict):
    cfg = dict(
        response_mime_type="application/json",
        response_schema=pv["output_schema"],
        system_instruction=pv["system_instruction"],
        max_output_tokens=16384,
    )
    # 3.x models reject thinking_budget (400); they take thinking_level. 2.5 keeps production's budget 0.
    if model.startswith("gemini-3"):
        # flash-lite accepts "minimal"; 3.8-flash rejects it ("Thinking level MINIMAL is not supported"), so use "low"
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level="minimal" if "lite" in model else "low")
    elif model.startswith("gemini-2.5"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    return cfg


def transcribe_batch(client, model, pv, seg_paths, batch_start):
    parts = [pv["user_prompt"]]
    for i, sp in enumerate(seg_paths, 1):
        parts += [
            f"\n<Segment {i}>\n",
            types.Part.from_bytes(data=sp.read_bytes(), mime_type="audio/mp3"),
            f"\n</Segment {i}>\n\n",
        ]
    cfg = gen_config(model, pv)
    last = None
    for attempt in range(4):
        try:
            t = time.time()
            r = client.models.generate_content(model=model, contents=parts, config=types.GenerateContentConfig(**cfg))
            dt = time.time() - t
            if not r.parsed:
                fr = r.candidates[0].finish_reason if r.candidates else None
                raise ValueError(f"no parsed output, finish={fr}")
            segs = r.parsed.get("segments", []) if isinstance(r.parsed, dict) else r.parsed.segments
            if len(segs) != len(seg_paths):
                raise ValueError(f"segment count mismatch: expected {len(seg_paths)} got {len(segs)}")
            u = r.usage_metadata
            return {
                "ok": True,
                "segments": segs,
                "latency": dt,
                "in": u.prompt_token_count,
                "out": (u.candidates_token_count or 0),
                "thoughts": (u.thoughts_token_count or 0),
                "attempts": attempt + 1,
            }
        except errors.ClientError as e:
            if e.code == 400 and "hinking level" in str(e) and "thinking_config" in cfg:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level="low")
                last = f"thinking_level fallback to low: {e}"
                continue
            if e.code == 400 and "hinking" in str(e) and "thinking_config" in cfg:
                cfg.pop("thinking_config")
                last = f"dropped thinking_config: {e}"
                continue
            if e.code == 429:
                time.sleep(20 * (attempt + 1))
                last = str(e)[:200]
                continue
            return {"ok": False, "error": str(e)[:300], "attempts": attempt + 1}
        except Exception as e:  # ValueError, ServerError
            last = str(e)[:300]
            time.sleep(5 * (attempt + 1))
    return {"ok": False, "error": last, "attempts": 4}


def run_segments(model: str, man, workers=3):
    client = genai.Client(api_key=KEY)
    pv = prompts()
    outdir = RESULTS / model
    outdir.mkdir(parents=True, exist_ok=True)

    def one(m):
        aid = m["audio_file_id"]
        outp = outdir / f"{aid}.json"
        if outp.exists():
            return aid, "cached"
        segs = split_segments(aid, HERE / m["local_audio"])
        t0 = time.time()
        windows = {}
        usage = {"in": 0, "out": 0, "thoughts": 0, "calls": 0, "failed_batches": 0}
        errs = []
        for bs in range(0, len(segs), BATCH):
            res = transcribe_batch(client, model, pv, segs[bs : bs + BATCH], bs)
            usage["calls"] += 1
            if not res["ok"]:
                usage["failed_batches"] += 1
                errs.append(res["error"])
                continue
            usage["in"] += res["in"]
            usage["out"] += res["out"]
            usage["thoughts"] += res["thoughts"]
            for s in res["segments"]:
                n = s["segment_number"] if isinstance(s, dict) else s.segment_number
                tx = s["transcript"] if isinstance(s, dict) else s.transcript
                windows[(bs + n - 1) * SEG_LEN] = tx
        pin, pout = PRICE.get(model, (0, 0))
        cost = usage["in"] / 1e6 * pin + (usage["out"] + usage["thoughts"]) / 1e6 * pout
        json.dump(
            {
                "audio_file_id": aid,
                "model": model,
                "method": "segments",
                "windows": {str(k): v for k, v in sorted(windows.items())},
                "usage": usage,
                "cost_usd": round(cost, 4),
                "wall_s": round(time.time() - t0, 1),
                "errors": errs,
            },
            open(outp, "w"),
            ensure_ascii=False,
            indent=1,
        )
        return (
            aid,
            f"{len(windows)} windows, {usage['failed_batches']} failed batches, ${cost:.3f}, {time.time() - t0:.0f}s",
        )

    with cf.ThreadPoolExecutor(workers) as ex:
        for aid, msg in ex.map(one, man):
            print(model, aid[:8], msg, flush=True)


# ---------------------------------------------------------------- B. gemini-3.5-transcribe (word timestamps)
LANG_CODES = {"Spanish": ["es-US"], "Arabic": ["ar-EG"], "English": ["en-US"]}
VARIANTS = ("lang", "diar", "lang+diar", "repeat")  # repeat = baseline body again (noise floor)


def transcription_config(variant: str | None, language: str) -> dict:
    """Request options per variant. variant=None is the original baseline body, unchanged."""
    mode = {"type": "verbatim", "timestamp_granularities": ["word"]}
    cfg = {"mode": mode}
    parts = set((variant or "").split("+")) - {""}
    if "lang" in parts:
        cfg["language_codes"] = LANG_CODES[language]
    if "diar" in parts:
        mode["diarization_mode"] = "speaker"
    return cfg


def run_transcribe(man, model="gemini-3.5-transcribe", workers=2, variant=None):
    client = genai.Client(api_key=KEY)
    outdir = RESULTS / (f"{model}@{variant}" if variant else model)
    outdir.mkdir(parents=True, exist_ok=True)

    def one(m):
        aid = m["audio_file_id"]
        outp = outdir / f"{aid}.json"
        if outp.exists():
            return aid, "cached"
        mp3 = HERE / m["local_audio"]
        src = mp3
        if m["duration_s"] > 1799.5:  # hard 30 min limit with timestamps; trim a hair
            src = HERE / "segments" / f"{aid}_trim.mp3"
            src.parent.mkdir(exist_ok=True)
            if not src.exists():
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", str(mp3), "-t", "1799", "-c", "copy", str(src)], check=True
                )
        t0 = time.time()
        f = client.files.upload(file=str(src), config=types.UploadFileConfig(mime_type="audio/mp3"))
        while f.state.name == "PROCESSING":
            time.sleep(1)
            f = client.files.get(name=f.name)
        body = {
            "model": f"models/{model}",
            "input": [{"type": "audio", "uri": f.uri, "mime_type": "audio/mp3"}],
            "generation_config": {"transcription_config": transcription_config(variant, m["language"])},
        }
        last = None
        for attempt in range(4):
            t_req = time.time()
            r = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/interactions",
                headers={"x-goog-api-key": KEY, "content-type": "application/json"},
                json=body,
                timeout=900,
            )
            if r.status_code == 200:
                req_s = time.time() - t_req
                break
            last = f"http {r.status_code}: {r.text[:300]}"
            if r.status_code in (429, 500, 503):
                time.sleep(30 * (attempt + 1))
                continue
            break
        try:
            client.files.delete(name=f.name)
        except Exception:
            pass
        if r.status_code != 200:
            json.dump(
                {"audio_file_id": aid, "model": model, "variant": variant, "method": "transcribe", "error": last,
                 "request": body["generation_config"]},
                open(outp, "w"),
            )
            return aid, f"FAILED {last}"
        d = r.json()
        if variant:  # keep the raw response so annotation shapes (speaker etc.) can be inspected
            json.dump(d, open(outdir / f"{aid}.raw.json", "w"), ensure_ascii=False)
        words = []
        text_parts = []
        for step in d.get("steps", []):
            for c in step.get("content", []):
                if c.get("text"):
                    text_parts.append(c["text"])
                for a in c.get("annotations", []) or []:
                    if a.get("type") == "word_info":
                        words.append(
                            {
                                "text": a["text"],
                                "start": float(a["start_offset"].rstrip("s")),
                                "end": float(a["end_offset"].rstrip("s")),
                                "speaker": a.get("speaker"),
                            }
                        )
        usage = d.get("usage", {})
        minutes = m["duration_s"] / 60
        cost = minutes * 0.003 + minutes * 0.002
        json.dump(
            {
                "audio_file_id": aid,
                "model": model,
                "method": "transcribe",
                "variant": variant,
                "request": body["generation_config"],
                "text": "\n".join(text_parts),
                "words": words,
                "windows": {str(k): v for k, v in sorted(windows_from_words(words).items())},
                "usage": usage,
                "cost_usd": round(cost, 4),
                "wall_s": round(time.time() - t0, 1),
                "request_s": round(req_s, 1),
                "status": d.get("status"),
            },
            open(outp, "w"),
            ensure_ascii=False,
        )
        return (
            aid,
            f"{len(words)} words, {len(text_parts)} text parts, status={d.get('status')}, {time.time() - t0:.0f}s",
        )

    with cf.ThreadPoolExecutor(workers) as ex:
        for aid, msg in ex.map(one, man):
            print(model, aid[:8], msg, flush=True)


# ---------------------------------------------------------------- report
def report(man, out_name="summary.json", only_models=None):
    models = sorted(p.name for p in RESULTS.iterdir() if p.is_dir())
    if only_models:
        models = [m for m in models if any(m == o or m.startswith(o) for o in only_models)]
    rows = []
    for m in man:
        aid = m["audio_file_id"]
        data = load_data(aid)
        ref = parse_ts_transcript(data["stage_1"]["timestamped_transcription"])
        cands = {}
        for model in models:
            p = RESULTS / model / f"{aid}.json"
            if p.exists():
                cands[model] = json.load(open(p))
        for model, c in cands.items():
            if "windows" not in c:
                rows.append({"id": aid[:8], "lang": m["language"], "model": model, "error": c.get("error", "?")})
                continue
            cw = {int(k): v for k, v in c["windows"].items()}
            sc = window_scores(ref, cw)
            row = {
                "id": aid[:8],
                "lang": m["language"],
                "station": m["station_code"],
                "model": model,
                "windows": len(cw),
                "sim_mean": sc["mean"],
                "p_ge70": sc["p_ge70"],
                "wer_vs_ref": wer(" ".join(ref[k] for k in sorted(ref)), " ".join(cw[k] for k in sorted(cw))),
                "cost": c.get("cost_usd"),
                "wall_s": c.get("wall_s"),
                "failed_batches": (c.get("usage") or {}).get("failed_batches"),
                "n_words": len(c.get("words", [])) or None,
                "request_s": c.get("request_s"),
                # share of reference windows (non-empty in ref) whose candidate window is empty
                "empty_win_share": round(
                    sum(1 for k in ref if norm(ref[k]) and not norm(cw.get(k, ""))) / max(1, sum(1 for k in ref if norm(ref[k]))),
                    3,
                ),
            }
            if c.get("words") and any(w.get("speaker") for w in c["words"]):
                row["n_speakers"] = len({w["speaker"] for w in c["words"] if w.get("speaker")})
            if c.get("method") == "transcribe":
                row["shift_test"] = {str(s): window_scores(ref, cw, shift=s)["mean"] for s in (-40, -20, 0, 20, 40)}
            # agreement with the other candidates (consensus proxy)
            others = [window_scores({int(k2): v2 for k2, v2 in o["windows"].items()}, cw)["mean"] for om, o in cands.items() if om != model and "windows" in o]
            row["agree_other_cands"] = (
                round(sum(x for x in others if x) / len([x for x in others if x]), 1) if any(others) else None
            )
            rows.append(row)
    out = RESULTS / out_name
    json.dump(rows, open(out, "w"), indent=1, ensure_ascii=False)
    # aggregate
    agg = {}
    for r in rows:
        if "error" in r:
            continue
        a = agg.setdefault(r["model"], {"n": 0, "sim": 0, "p70": 0, "wer": 0, "cost": 0, "wall": 0, "nwer": 0})
        a["n"] += 1
        a["sim"] += r["sim_mean"] or 0
        a["p70"] += r["p_ge70"] or 0
        a["cost"] += r["cost"] or 0
        a["wall"] += r["wall_s"] or 0
        if r["wer_vs_ref"] is not None:
            a["wer"] += r["wer_vs_ref"]
            a["nwer"] += 1
    print(f"{'model':26s} {'files':>5s} {'sim_mean':>8s} {'p>=70':>6s} {'WER':>6s} {'$/file':>7s} {'s/file':>7s}")
    for model, a in agg.items():
        n = a["n"] or 1
        print(
            f"{model:26s} {a['n']:5d} {a['sim'] / n:8.1f} {a['p70'] / n:6.2f} {(a['wer'] / a['nwer']) if a['nwer'] else float('nan'):6.3f} {a['cost'] / n:7.3f} {a['wall'] / n:7.0f}"
        )
    print("per-file rows:", out)
    for r in rows:
        if "error" in r:
            print("  ERROR", r)
        elif "shift_test" in r:
            print("  shift", r["model"], r["id"], r["lang"], r["shift_test"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["segments", "transcribe", "report"])
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--variant", choices=VARIANTS)
    ap.add_argument("--models", help="report: comma list of model dirs (prefix match) to include")
    ap.add_argument("--out", default="summary.json", help="report: output file name under results/")
    a = ap.parse_args()
    man = load_manifest(a.ids.split(",") if a.ids else None, a.limit)
    if a.cmd == "segments":
        run_segments(a.model, man, a.workers)
    elif a.cmd == "transcribe":
        run_transcribe(man, workers=a.workers, variant=a.variant)
    else:
        report(man, a.out, a.models.split(",") if a.models else None)
