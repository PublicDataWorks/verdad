"""Parallel Decisions eval for VERDAD Stage 3 clips.

Route: MCP streamable HTTP `web_decisions` (no key) by default; if PARALLEL_API_KEY is set (or --api),
POST https://api.parallel.ai/v1/decisions with x-api-key. Read-only; no production writes.
"""
import argparse, concurrent.futures as cf, json, os, sys, time, threading
import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results_parallel")
MCP_URL = "https://mcp.parallel.ai/mcp"
API_URL = "https://api.parallel.ai/v1/decisions"
HDR = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

CATS = {
    "none": "The central claim is not misinformation: opinion, religious teaching, accurate news, or a claim reliable sources support.",
    "Women's Health and Reproductive Care": "Claims about women's health, sterilization, pregnancy, cancer screening or reproductive care.",
    "Children's Health and Pediatric Care": "Claims about infant or child health, feeding, vaccines or pediatric treatment.",
    "Abortion and Reproductive Rights": "Claims about abortion law, safety or reproductive rights.",
    "Contraception and Family Planning": "Claims about contraception, vasectomy or family planning.",
    "LGBTQ+ Rights and Gender Issues": "Claims about LGBTQ+ people, gender identity or gender medicine.",
    "Culture Wars and Social Issues": "Claims about contested social or cultural issues.",
    "Political Figures and Movements": "Claims about politicians, parties or political movements.",
    "Election Integrity and Voting Processes": "Claims about voting, election fraud or election procedures.",
    "Conspiracy Theories": "Claims resting on a hidden-plot or secret-coordination narrative.",
    "Foreign Policy and International Relations": "Claims about foreign governments, wars or diplomacy.",
    "Geopolitical Issues": "Claims about regional power, borders, territory or resources.",
    "Public Safety and Law Enforcement": "Claims about crime, policing or public safety.",
    "Healthcare Reform": "Claims about health policy, insurance or medical regulation.",
    "Other health or medical (supplements, cures, alternative medicine)": "Health claims about supplements, miracle cures or alternative treatments not covered above.",
}
SCORE_LEVELS = [  # index 0..4 -> x25
    "Nothing relevant: no reliable source addresses the claim.",
    "Thin: only low-quality, promotional or tangential sources.",
    "Partial: some reliable sources touch the topic but not the specific claim.",
    "Good: reliable sources directly address the claim, though not conclusively.",
    "Strong: authoritative sources (agencies, peer-reviewed work, major outlets) directly confirm or refute the claim.",
]


def build(snip, variant):
    d = snip["data"]; af = d["audio_file"]
    if variant == "A":   # as specified: station metadata + transcript + production explanation
        state = {"station": f"{af['radio_station_name']} ({af['radio_station_code']})", "state": af.get("location_state"),
                 "recorded_at": af["recorded_at"], "language": snip["lang"], "claim_transcript": snip["transcript"],
                 "claim_description_in_english": snip["explanation"]}
    elif variant == "C":  # claim-centric: no station, keeps production explanation
        state = {"language": snip["lang"], "claim_transcript": snip["transcript"], "claim_description_in_english": snip["explanation"]}
    elif variant in ("D", "E"):  # claim-centric and blind: transcript only, no production explanation
        state = {"language": snip["lang"], "claim_transcript": snip["transcript"]}
    else:                 # B: station metadata, transcript only
        state = {"station": f"{af['radio_station_name']} ({af['radio_station_code']})", "state": af.get("location_state"),
                 "recorded_at": af["recorded_at"], "language": snip["lang"], "claim_transcript": snip["transcript"]}
    asof = af["recorded_at"][:10]
    q = {
        "is_false": {
            "type": "noul",
            "instructions": f"As of {asof} (the broadcast date), is the central factual claim in `claim_transcript` false or misleading according to reliable sources? Judge facts, not opinions, religious teaching or predictions.",
            "criteria": {
                "true": "Reliable sources (agencies, medical bodies, major fact-checkers, primary documents) contradict the claim or show it is materially misleading.",
                "false": "Reliable sources support the claim, or it is opinion, religious teaching or prediction that is not a checkable factual claim.",
            },
        },
        "category": {
            "type": "choice",
            "instructions": f"Which misinformation category best fits the central claim in `claim_transcript`? Choose `none` if it is not misinformation as of {asof}.",
            "criteria": CATS,
        },
        "evidence_quality": {
            "type": "score",
            "instructions": f"How well can the central claim in `claim_transcript` be verified or refuted from sources available as of {asof}?",
            "criteria": SCORE_LEVELS,
        },
    }
    if variant == "E":   # neutral wording, claim-only, no 'misinformation' vocabulary anywhere
        q = {
            "supported": {
                "type": "noul",
                "instructions": f"As of {asof}, is the main factual statement made in `claim_transcript` accurate according to reliable sources?",
                "criteria": {"true": "Reliable sources confirm the statement.", "false": "Reliable sources contradict the statement or show it is wrong."},
            },
            "evidence_quality": q["evidence_quality"],
        }
    return {"state": state, "questions": q, "advanced_settings": {"include_excerpts": True}}


def parse_sse(text):
    out = None
    for line in text.split("\n"):
        if line.startswith("data:"):
            try: out = json.loads(line[5:].strip())
            except Exception: pass
    return out


class Mcp:
    def __init__(self):
        self.c = httpx.Client(timeout=180)
        self.h = dict(HDR); self.n = 0; self.lock = threading.Lock()
        r = self.c.post(MCP_URL, headers=self.h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "verdad-eval", "version": "0.1"}}})
        r.raise_for_status()
        sid = r.headers.get("mcp-session-id")
        if sid: self.h["Mcp-Session-Id"] = sid
        self.c.post(MCP_URL, headers=self.h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, args):
        with self.lock:
            self.n += 1; i = 100 + self.n
        r = self.c.post(MCP_URL, headers=self.h, json={"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "web_decisions", "arguments": args}})
        body = parse_sse(r.text) if "event-stream" in r.headers.get("content-type", "") else (r.json() if r.text else None)
        if body and "result" in body:
            res = body["result"]
            if res.get("isError"):
                return r.status_code, None, json.dumps(res)[:4000]
            sc = res.get("structuredContent")
            if sc is None:
                try: sc = json.loads(res["content"][0]["text"])
                except Exception: return r.status_code, None, json.dumps(res)[:4000]
            return r.status_code, sc, None
        return r.status_code, None, (json.dumps(body) if body else r.text)[:4000]


def api_call(args):
    r = httpx.post(API_URL, headers={"x-api-key": os.environ["PARALLEL_API_KEY"], "Content-Type": "application/json"}, json=args, timeout=180)
    try: return r.status_code, r.json(), None
    except Exception: return r.status_code, None, r.text[:2000]


def load():
    sel = json.load(open(os.path.join(HERE, "snippets/selection.json")))
    snips = []
    for s in sel:
        d = json.load(open(os.path.join(HERE, f"data/{s['audio_file_id']}.json")))
        sn = next(x for x in d["snippets"] if x["id"] == s["snippet_id"])
        fl = next((x for x in d["stage_1"]["flagged_snippets"] if x["uuid"] == s["snippet_id"]), None)
        if fl:
            transcript, expl = fl["transcription"], fl["explanation"]
        else:
            claims = (sn["confidence_scores"].get("analysis") or {}).get("claims") or []
            transcript = sn["transcription"][:3500]
            expl = "; ".join(c["quote"] for c in claims) or ("(no production claim extracted) " + (sn["title"] or {}).get("english", ""))
        snips.append({**s, "data": d, "transcript": transcript, "explanation": expl})
    return snips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A", choices=["A", "B", "C", "D", "E"])
    ap.add_argument("--ids"); ap.add_argument("--limit", type=int); ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--repeat", action="store_true"); ap.add_argument("--api", action="store_true"); ap.add_argument("--redo", action="store_true")
    a = ap.parse_args()
    use_api = a.api or bool(os.environ.get("PARALLEL_API_KEY"))
    os.makedirs(OUT, exist_ok=True)
    snips = load()
    if a.ids: snips = [s for s in snips if s["snippet_id"][:8] in a.ids.split(",")]
    if a.limit: snips = snips[: a.limit]
    mcp = None if use_api else Mcp()

    def run(s):
        os.makedirs(os.path.join(OUT, "repeat"), exist_ok=True)
        p = os.path.join(OUT, "repeat" if a.repeat else "", f"{s['snippet_id']}.{a.variant}.json")
        if os.path.exists(p) and not a.redo:
            try:
                if json.load(open(p)).get("http") == 200: return s["snippet_id"], "cached"
            except Exception: pass
        args = build(s, a.variant)
        tries = 0
        while True:
            t = time.time()
            try:
                code, body, raw = api_call(args) if use_api else mcp.call(args)
            except Exception as e:
                code, body, raw = -1, None, repr(e)
            lat = time.time() - t  # latency of the final attempt only
            limited = code == 429 or (raw and "rate limit" in raw)
            if not limited or tries >= 8: break
            tries += 1; time.sleep(min(15 * tries, 90))
        rec = {"snippet_id": s["snippet_id"], "variant": a.variant, "route": "api" if use_api else "mcp", "latency_s": round(lat, 2), "rate_limit_retries": tries, "http": code, "request": args, "raw": body, "raw_text": raw}
        json.dump(rec, open(p, "w"), ensure_ascii=False, indent=1)
        return s["snippet_id"], f"{code} {lat:.1f}s"

    with cf.ThreadPoolExecutor(a.workers) as ex:
        for sid, msg in ex.map(run, snips):
            print(sid[:8], msg, flush=True)


if __name__ == "__main__":
    main()
