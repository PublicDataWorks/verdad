"""Matrix of human-labelled snippet hits per model dir, plus flags that match no production flag (candidate new false flags)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from detection_eval import overlap, RESULTS, HERE
from rapidfuzz import fuzz
models = sys.argv[1].split(",")
show_new = len(sys.argv) > 2
man = json.load(open(HERE / "data" / "manifest.json"))
rows = []
newflags = {m: [] for m in models}
for m in man:
    aid = m["audio_file_id"]
    d = json.load(open(HERE / "data" / f"{aid}.json"))
    ref = d["stage_1"]["flagged_snippets"] or []
    byu = {x["uuid"]: x for x in ref}
    hum = [(s["id"], byu[s["id"]]) for s in d["snippets"] if s["human_labels"] and s["id"] in byu]
    res = {}
    for mod in models:
        p = RESULTS / mod / f"{aid}.json"
        r = json.load(open(p)) if p.exists() else {}
        res[mod] = (r.get("result") or {}).get("flagged_snippets", []) if r.get("ok") else None
        for c in res[mod] or []:
            if not any(overlap(c, x) > 0 or fuzz.partial_ratio((c.get("transcription") or "")[:200], x.get("transcription") or "") >= 80 for x in ref):
                newflags[mod].append((aid[:8], c["start_time"], c["end_time"], c["explanation"][:170]))
    for uid, h in hum:
        cells = []
        for mod in models:
            c = res[mod]
            cells.append("-" if c is None else ("X" if any(overlap(x, h) > 0 for x in c) else "."))
        print(f"{aid[:8]} {h['start_time']:>6} {' '.join(f'{x:^5}' for x in cells)}  {h['explanation'][:70]}")
print("cols:", " | ".join(models))
if show_new:
    for mod in models:
        print(f"\n## flags with no production match: {mod} ({len(newflags[mod])})")
        for x in newflags[mod]:
            print("  ", *x)
