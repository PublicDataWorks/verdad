"""For one model: per human-labelled snippet, hits across baseline runs vs variant runs (with Stage 3 title), and
variant flags that match no production flag."""
import json, sys, ast
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from detection_eval import overlap, RESULTS, HERE
from rapidfuzz import fuzz
base = sys.argv[1].split(","); var = sys.argv[2].split(",")
man = json.load(open(HERE / "data" / "manifest.json"))
def load(mod, aid):
    p = RESULTS / mod / f"{aid}.json"
    if not p.exists(): return None
    r = json.load(open(p)); return (r.get("result") or {}).get("flagged_snippets", []) if r.get("ok") else None
def title(s):
    t = s["title"]
    if isinstance(t, dict): return t.get("english")
    try: return ast.literal_eval(t)["english"]
    except Exception: return str(s["title"])[:90]
print("baseline:", base, "\nvariant:", var)
for m in man:
    aid = m["audio_file_id"]; d = json.load(open(HERE / "data" / f"{aid}.json"))
    ref = d["stage_1"]["flagged_snippets"] or []; byu = {x["uuid"]: x for x in ref}
    for s in d["snippets"]:
        if not (s["human_labels"] and s["id"] in byu): continue
        h = byu[s["id"]]
        b = [load(x, aid) for x in base]; v = [load(x, aid) for x in var]
        bh = sum(1 for c in b if c is not None and any(overlap(x, h) > 0 for x in c)); bn = sum(c is not None for c in b)
        vh = sum(1 for c in v if c is not None and any(overlap(x, h) > 0 for x in c)); vn = sum(c is not None for c in v)
        mark = "GAIN" if vh / max(vn, 1) > bh / max(bn, 1) else ("LOSS" if vh / max(vn, 1) < bh / max(bn, 1) else "")
        print(f"  {aid[:8]} {h['start_time']:>6} base {bh}/{bn} var {vh}/{vn} {mark:4} {title(s)}")
print("\nvariant flags with no production match:")
for m in man:
    aid = m["audio_file_id"]; d = json.load(open(HERE / "data" / f"{aid}.json")); ref = d["stage_1"]["flagged_snippets"] or []
    for mod in var:
        for c in load(mod, aid) or []:
            if not any(overlap(c, x) > 0 or fuzz.partial_ratio((c.get("transcription") or "")[:200], x.get("transcription") or "") >= 80 for x in ref):
                print(f"  [{mod.split('+')[-1]}] {aid[:8]} {c['start_time']}-{c['end_time']} {c['explanation'][:160]}")
