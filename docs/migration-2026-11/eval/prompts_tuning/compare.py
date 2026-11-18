"""Per-file comparison: human-labelled regions and which model results hit them."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from detection_eval import overlap, RESULTS, HERE

models = sys.argv[1].split(",")
ids = sys.argv[2].split(",") if len(sys.argv) > 2 else None
man = json.load(open(HERE / "data" / "manifest.json"))
for m in man:
    aid = m["audio_file_id"]
    if ids and aid[:8] not in ids:
        continue
    d = json.load(open(HERE / "data" / f"{aid}.json"))
    ref = {x["uuid"]: x for x in d["stage_1"]["flagged_snippets"] or []}
    print(f"\n=== {aid[:8]} {m['station_code']} ({len(ref)} prod flags)")
    hum = [ref[s["id"]] for s in d["snippets"] if s["human_labels"] and s["id"] in ref]
    for h in hum:
        print(f"  HUMAN {h['start_time']}-{h['end_time']}: {h['explanation'][:150]}")
    for mod in models:
        p = RESULTS / mod / f"{aid}.json"
        if not p.exists():
            print(f"  [{mod}] missing"); continue
        r = json.load(open(p))
        if not r.get("ok"):
            print(f"  [{mod}] FAIL"); continue
        cand = (r["result"] or {}).get("flagged_snippets", []) or []
        hits = sum(1 for h in hum if any(overlap(c, h) > 0 for c in cand))
        print(f"  [{mod}] {len(cand)} flags, human-hit {hits}/{len(hum)}")
        for c in cand:
            print(f"     {c['start_time']}-{c['end_time']} {'H' if any(overlap(c,h)>0 for h in hum) else ' '} {c['explanation'][:130]}")
