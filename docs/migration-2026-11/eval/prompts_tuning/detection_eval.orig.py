"""Stage 1 main-detection eval: same production transcript in, compare flagged snippets across models.

Input per file: the production gemini-2.5-flash timestamped transcript (so this isolates the detection model from the
transcription model). Reference: the production detection_result (2.5 Flash) plus human labels on the resulting snippets.

Backends:
  api    : Gemini Developer API with the eval key (gemini-3.x, gemma-4-*)
  vertex : Vertex AI OpenAI-compatible endpoint (gemma-4-26b-a4b-it-maas) with gcloud ADC, project verdad-435408

Usage: python detection_eval.py run --model gemini-3.5-flash-lite [--backend api|vertex] [--ids ..] [--limit N]
       python detection_eval.py report
"""

import argparse
import json
import re
import subprocess
import time
import concurrent.futures as cf
from datetime import datetime, timezone
from pathlib import Path

import requests
from rapidfuzz import fuzz
from google import genai
from google.genai import types, errors

HERE = Path(__file__).resolve().parent
REPO = Path("/Users/j/GitHub/verdad")
KEY = (HERE.parent / "secrets" / "gemini_eval_key.txt").read_text().strip()
RESULTS = HERE / "results_detection"
PRICE = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (0.30, 2.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
    "gemma-4-31b-it": (0, 0),
    "gemma-4-26b-a4b-it": (0, 0),
    "gemma-4-26b-a4b-it-maas": (0.0, 0.0),
    "gemini-2.5-flash": (0.30, 2.50),
}


def prompts():
    p = REPO / "prompts" / "stage_1" / "main"
    return {
        "system_instruction": (p / "detection_system_instruction.md").read_text(),
        "user_prompt": (p / "detection_user_prompt.md").read_text(),
        "output_schema": json.load(open(p / "detection_output_schema.json")),
    }


def metadata(af: dict) -> dict:
    rec = datetime.fromisoformat(af["recorded_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    # mirror processing_pipeline.stage_1.tasks.get_audio_file_metadata + temporal_context, frozen "now" = recording day for comparability
    return {
        "radio_station_name": af["radio_station_name"],
        "radio_station_code": af["radio_station_code"],
        "location": {"state": af["location_state"], "city": af["location_city"]},
        "recorded_at": rec.strftime("%B %-d, %Y %-I:%M %p"),
        "recording_day_of_week": rec.strftime("%A"),
        "time_zone": "UTC",
        "current_date_time": rec.strftime("%B %-d, %Y %-I:%M %p UTC"),
        "temporal_notice": "Treat the recording date as the present; do not assume knowledge of later events.",
    }


def build_user_prompt(pv, data):
    return pv["user_prompt"].format(
        kb_context="",
        metadata=json.dumps(metadata(data["audio_file"]), indent=2),
        timestamped_transcription=data["stage_1"]["timestamped_transcription"],
    )


def call_api(client, model, pv, user_prompt, level="high"):
    cfg = dict(
        response_mime_type="application/json",
        response_schema=pv["output_schema"],
        system_instruction=pv["system_instruction"],
        max_output_tokens=16384,
    )
    # production uses thinking_budget=4096 on 2.5 Flash; 3.x takes thinking_level, so use "high" for parity
    if model.startswith("gemini-3"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=level)
    elif model.startswith("gemini-2.5"):
        cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=4096)
    last = None
    for attempt in range(5):
        try:
            t = time.time()
            r = client.models.generate_content(
                model=model, contents=[user_prompt], config=types.GenerateContentConfig(**cfg)
            )
            parsed = r.parsed
            if not parsed:
                try:
                    parsed = json.loads(r.text or "")
                except Exception:
                    fin = r.candidates[0].finish_reason if r.candidates else None
                    raise ValueError(f"no parsed output; finish={fin}; text_head={(r.text or '')[:160]!r}")
            u = r.usage_metadata
            return {
                "ok": True,
                "result": r.parsed,
                "latency": round(time.time() - t, 1),
                "in": u.prompt_token_count,
                "out": u.candidates_token_count or 0,
                "thoughts": u.thoughts_token_count or 0,
                "attempts": attempt + 1,
            }
        except errors.ClientError as e:
            last = str(e)[:400]
            print(f"  [{model}] attempt {attempt + 1}: {last[:140]}", flush=True)
            if e.code == 400 and "hinking level" in str(e):
                cfg["thinking_config"] = types.ThinkingConfig(thinking_level="low")
                continue
            if e.code == 400 and "hinking" in str(e):
                cfg.pop("thinking_config", None)
                continue
            if e.code == 429:
                # Gemma on the free tier is capped at 16k input tokens/minute: wait out a full minute per attempt
                time.sleep((65 if model.startswith("gemma") else 25) * (attempt + 1))
                continue
            return {"ok": False, "error": last}
        except Exception as e:
            last = str(e)[:400]
            time.sleep(5 * (attempt + 1))
    return {"ok": False, "error": last}


def call_vertex(model, pv, user_prompt):
    tok = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
    body = {
        "model": f"google/{model}",
        "messages": [{"role": "system", "content": pv["system_instruction"]}, {"role": "user", "content": user_prompt}],
        "max_tokens": 16384,
        "response_format": {"type": "json_schema", "json_schema": {"name": "detection", "schema": pv["output_schema"]}},
    }
    last = None
    for attempt in range(4):
        t = time.time()
        r = requests.post(
            "https://aiplatform.googleapis.com/v1/projects/verdad-435408/locations/global/endpoints/openapi/chat/completions",
            headers={"Authorization": f"Bearer {tok}", "content-type": "application/json"},
            json=body,
            timeout=600,
        )
        if r.status_code == 200:
            d = r.json()
            txt = d["choices"][0]["message"]["content"]
            try:
                parsed = json.loads(txt)
            except Exception:
                m = re.search(r"\{.*\}", txt, re.S)
                parsed = json.loads(m.group(0)) if m else None
            if parsed is None:
                return {"ok": False, "error": "unparseable JSON: " + txt[:200]}
            u = d.get("usage", {})
            return {
                "ok": True,
                "result": parsed,
                "latency": round(time.time() - t, 1),
                "in": u.get("prompt_tokens"),
                "out": u.get("completion_tokens"),
                "thoughts": 0,
                "attempts": attempt + 1,
            }
        last = f"http {r.status_code}: {r.text[:300]}"
        if r.status_code in (429, 500, 503):
            time.sleep(20 * (attempt + 1))
            continue
        break
    return {"ok": False, "error": last}


def run(model, backend, man, workers, level="high"):
    pv = prompts()
    client = genai.Client(api_key=KEY) if backend == "api" else None
    suffix = f"@{level}" if (backend == "api" and model.startswith("gemini-3") and level != "high") else ""
    outdir = RESULTS / (model + suffix)
    outdir.mkdir(parents=True, exist_ok=True)

    def one(m):
        aid = m["audio_file_id"]
        outp = outdir / f"{aid}.json"
        if outp.exists() and json.load(open(outp)).get("ok"):
            return aid, "cached"
        data = json.load(open(HERE / "data" / f"{aid}.json"))
        up = build_user_prompt(pv, data)
        res = call_api(client, model, pv, up, level) if backend == "api" else call_vertex(model, pv, up)
        pin, pout = PRICE.get(model, (0, 0))
        if res["ok"]:
            res["cost_usd"] = round(
                (res["in"] or 0) / 1e6 * pin + ((res["out"] or 0) + (res["thoughts"] or 0)) / 1e6 * pout, 4
            )
        res.update(audio_file_id=aid, model=model, backend=backend, prompt_chars=len(up))
        json.dump(res, open(outp, "w"), ensure_ascii=False, indent=1)
        n = len((res.get("result") or {}).get("flagged_snippets", [])) if res["ok"] else None
        return aid, (
            f"{n} flagged, in={res['in']} out={res['out']} thoughts={res['thoughts']} {res['latency']}s ${res['cost_usd']}"
            if res["ok"]
            else f"FAILED {res['error'][:160]}"
        )

    with cf.ThreadPoolExecutor(workers) as ex:
        for aid, msg in ex.map(one, man):
            print(model, aid[:8], msg, flush=True)


def to_s(ts):
    try:
        p = [int(x) for x in str(ts).split(":")]
        return p[-1] + 60 * p[-2] + (3600 * p[-3] if len(p) == 3 else 0)
    except Exception:
        return None


def overlap(a, b):
    s1, e1 = to_s(a["start_time"]), to_s(a["end_time"])
    s2, e2 = to_s(b["start_time"]), to_s(b["end_time"])
    if None in (s1, e1, s2, e2):
        return 0
    return max(0, min(e1, e2) + 20 - max(s1, s2))  # windows are 20 s wide; end tag is a window start


def report(man):
    models = sorted(p.name for p in RESULTS.iterdir() if p.is_dir())
    print(
        f"{'model':28s} {'files':>5s} {'flags/file':>10s} {'ref flags':>9s} {'recall@ref':>10s} {'prec@ref':>8s} {'human-hit':>9s} {'in tok':>7s} {'$/file':>7s} {'s/file':>6s} {'fails':>5s}"
    )
    for model in models:
        n = 0
        flags = 0
        reff = 0
        tp = 0
        fp = 0
        hum_hit = 0
        hum_tot = 0
        tin = 0
        cost = 0
        lat = 0
        fails = 0
        for m in man:
            p = RESULTS / model / f"{m['audio_file_id']}.json"
            if not p.exists():
                continue
            r = json.load(open(p))
            if not r.get("ok"):
                fails += 1
                continue
            data = json.load(open(HERE / "data" / f"{m['audio_file_id']}.json"))
            ref = data["stage_1"]["flagged_snippets"] or []
            cand = (r["result"] or {}).get("flagged_snippets", []) or []
            n += 1
            flags += len(cand)
            reff += len(ref)
            tin += r["in"] or 0
            cost += r.get("cost_usd", 0)
            lat += r["latency"]
            matched_ref = set()
            for c in cand:
                hit = [
                    i
                    for i, x in enumerate(ref)
                    if overlap(c, x) > 0
                    or fuzz.partial_ratio((c.get("transcription") or "")[:200], (x.get("transcription") or "")) >= 80
                ]
                if hit:
                    tp += 1
                    matched_ref.update(hit)
                else:
                    fp += 1
            # human-labeled snippets: did the candidate flag the same region?
            by_uuid = {x.get("uuid"): x for x in ref}
            for s in data["snippets"]:
                if s["human_labels"]:
                    hum_tot += 1
                    x = by_uuid.get(s["id"])
                    if x and any(overlap(c, x) > 0 for c in cand):
                        hum_hit += 1
        if n:
            print(
                f"{model:28s} {n:5d} {flags / n:10.1f} {reff / n:9.1f} {tp / max(1, reff):10.2f} {tp / max(1, tp + fp):8.2f} {f'{hum_hit}/{hum_tot}':>9s} {tin / n:7.0f} {cost / n:7.3f} {lat / n:6.0f} {fails:5d}"
            )
        else:
            print(f"{model:28s} no results; fails={fails}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--model", default="gemini-3.5-flash-lite")
    ap.add_argument("--backend", default="api", choices=["api", "vertex"])
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3); ap.add_argument("--level", default="high")
    a = ap.parse_args()
    man = json.load(open(HERE / "data" / "manifest.json"))
    if a.ids:
        w = a.ids.split(",")
        man = [m for m in man if m["audio_file_id"] in w or m["audio_file_id"][:8] in w]
    if a.limit:
        man = man[: a.limit]
    if a.cmd == "run":
        run(a.model, a.backend, man, a.workers, a.level)
    else:
        report(man)
