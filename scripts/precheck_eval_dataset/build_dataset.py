"""Build the VER-475 pre-check eval set (docs/PRECHECK_EVALUATION.md, "Rebuilding the eval set").

The SQL in sql/ runs read-only against production, either through the Supabase MCP tool (save each result to a
file) or with psql. This script never connects to anything; it only reads the saved results.

  python3 -I build_dataset.py render-sql --prefixes 1,2,3      # details.sql with the page filled in, for MCP use
  python3 -I build_dataset.py sample --population POP --out DIR   # draw a fresh stratified sample (seed 475)
  python3 -I build_dataset.py build --population POP --details 'DIR/details_*.txt' --out DIR [--ids ids.json]

With --ids (default: the committed ids.json) the build keeps exactly those clips, strata and weights, so it rebuilds
the published set. With --ids none it draws the sample from the population again.
Outputs in --out: precheck_eval.jsonl, ids.json, build_report.json. Keep them out of the repo (the JSONL holds
transcripts).
"""

import argparse
import glob
import hashlib
import json
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mcp_result import load_agg  # noqa: E402

SEED = 475
LIVE_SINCE = "2026-11-06"
SAMPLE_SIZES = {"g35_80_89": 500, "g35_40_79": 300, "g35_lt40": 700}  # g38_all and g35_90plus: take every clip
PAGES = ["0", "1,2,3", "4,5,6", "7,8,9", "a,b,c", "d,e,f"]
DEFAULT_IDS = os.path.join(HERE, "ids.json")


def stage3_overall(p):
    """The Stage 3 score: Stage 4 copies the row into previous_analysis before it overwrites the score."""
    return int(p["prev_overall"] if p["has_prev"] else p["final_overall"])


def band(x):
    return "90+" if x >= 90 else "80-89" if x >= 80 else "40-79" if x >= 40 else "<40"


def stratum(p):
    if p["analyzed_by"] == "gemini-3.8-flash":
        return "g38_all"
    return {"90+": "g35_90plus", "80-89": "g35_80_89", "40-79": "g35_40_79", "<40": "g35_lt40"}[band(stage3_overall(p))]


def split_of(snippet_id):
    return "dev" if int(hashlib.md5(snippet_id.encode()).hexdigest(), 16) % 2 == 0 else "test"


def draw_sample(population):
    by_stratum = defaultdict(list)
    for p in sorted(population, key=lambda p: p["id"]):
        by_stratum[stratum(p)].append(p["id"])
    rng = random.Random(SEED)
    chosen = {}
    for name in sorted(by_stratum):
        ids = by_stratum[name]
        n = SAMPLE_SIZES.get(name)
        chosen[name] = ids if n is None or n >= len(ids) else sorted(rng.sample(ids, n))
    return by_stratum, chosen


def render_details_sql(prefixes):
    if not re.fullmatch(r"[0-9a-f](,[0-9a-f])*", prefixes):
        raise SystemExit("--prefixes must be hex digits separated by commas, e.g. 1,2,3")
    with open(os.path.join(HERE, "sql", "details.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    return sql.replace(":'prefixes'", f"'{prefixes}'")


# --- Stage 1 language guess (from the Stage 1 transcript only, never from Stage 3) ---------------------------------
_ARABIC = re.compile(r"[؀-ۿ]")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_VIET = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.I)
_ES = {"el", "la", "los", "las", "de", "que", "y", "en", "es", "por", "para", "con", "una", "un", "no", "se", "lo",
       "del", "pero", "como", "más", "muy", "está", "porque", "nosotros", "ellos"}
_EN = {"the", "and", "of", "to", "is", "that", "in", "it", "you", "we", "they", "this", "for", "with", "are", "was",
       "but", "not", "have", "be", "what", "on"}
_HT = {"mwen", "nou", "yo", "pou", "ki", "nan", "sa", "li", "pa", "ak", "gen", "se", "ou", "konsa", "tout", "yon"}


def guess_language(text):
    """Script and stopword heuristic over the Stage 1 excerpt. Returns (language or None, share)."""
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return None, 0.0
    for pattern, name, cutoff in ((_ARABIC, "Arabic", 0.3), (_CYRILLIC, "Russian", 0.3), (_VIET, "Vietnamese", 0.03)):
        share = len(pattern.findall(text)) / len(letters)
        if share > cutoff:
            return name, round(share, 2)
    tokens = re.findall(r"[a-záéíóúñü']+", text.lower())
    if not tokens:
        return None, 0.0
    scores = {
        "Spanish": sum(t in _ES for t in tokens),
        "English": sum(t in _EN for t in tokens),
        "Haitian Creole": sum(t in _HT for t in tokens),
    }
    lang = max(scores, key=scores.get)
    share = scores[lang] / len(tokens)
    return (lang, round(share, 2)) if share >= 0.05 else (None, round(share, 2))


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))] if values else None


def make_record(sid, p, d, stratum_name):
    f = d["flagged"]
    fs_s, fe_s = float(d["flag_start_s"]), float(d["flag_end_s"])
    clip_start, clip_end = float(d["clip_start_s"]), float(d["clip_end_s"])
    known = {"uuid", "start_time", "end_time", "explanation", "keywords_detected", "disinformation_categories",
             "transcription"}
    lang, lang_share = guess_language(d["clip_excerpt"])
    return {
        "snippet_id": sid,
        "split": split_of(sid),
        "stratum": stratum_name,
        "weight": None,
        "label": {
            "stage3_overall": stage3_overall(p),
            "final_overall": int(p["final_overall"]) if p["final_overall"] is not None else None,
            "stage4_changed_score": bool(p["has_prev"]) and stage3_overall(p) != int(p["final_overall"]),
            "reviewed_by_stage4": p["reviewed_at"] is not None,
            "analyzed_by": p["analyzed_by"],
            "status": p["status"],
            "stage3_prompt_version_id": p["prev_prompt_version_id"] if p["has_prev"] else p["stage3_prompt_version_id"],
            "analyzed_at": p["prev_updated_at"] if p["has_prev"] else p["updated_at"],
            "analyzed_at_source": "previous_analysis.updated_at" if p["has_prev"] else "snippets.updated_at",
        },
        "meta": {
            "station_code": d["station_code"] or p["station_code"],
            "station_name": d["station_name"],
            "location_state": d["location_state"] or p["location_state"],
            "location_city": d["location_city"],
            "recorded_at": p["recorded_at"],
            "stage3_language": p["lang_prev"] if p["has_prev"] else p["lang_final"],
            "live": p["recorded_at"] >= LIVE_SINCE,
            "priority": p["priority"],
        },
        "input": {
            "stage1_explanation": f.get("explanation"),
            "stage1_keywords": f.get("keywords_detected") or [],
            "stage1_categories": f.get("disinformation_categories") or [],
            "stage1_transcript_excerpt": d["clip_excerpt"],
            "start_time": f.get("start_time"),
            "end_time": f.get("end_time"),
            "duration_s": round(fe_s - fs_s, 1),
            "stage1_transcriptor": d["transcriptor"],
            "stage1_language": lang,
            "stage1_extra": {
                "flagged_transcription": f.get("transcription"),
                "core_excerpt": d.get("core_excerpt") or "",
                "clip_start_s": clip_start,
                "clip_end_s": clip_end,
                "clip_duration_s": round(clip_end - clip_start, 1),
                "n_flagged_in_recording": d["n_flagged"],
                "flagged_index": d["flagged_index"],
                "recording_words_total": d["n_words_total"],
                "stage1_language_heuristic_share": lang_share,
                "detection_prompt_version_id": d["detection_prompt_version_id"],
                "transcription_prompt_version_id": d["transcription_prompt_version_id"],
                "audio_recorded_at": d["audio_recorded_at"],
                "other_flagged_fields": {k: v for k, v in f.items() if k not in known},
            },
        },
    }


def cmd_render_sql(args):
    sys.stdout.write(render_details_sql(args.prefixes))


def cmd_sample(args):
    by_stratum, chosen = draw_sample(load_agg(args.population))
    plan = {"seed": SEED, "sample_sizes_requested": SAMPLE_SIZES,
            "strata": {k: {"population": len(by_stratum[k]), "sample": len(chosen[k])} for k in sorted(by_stratum)},
            "ids": chosen}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "sample_plan.json"), "w") as fh:
        json.dump(plan, fh, indent=1)
    print(json.dumps(plan["strata"], indent=1))


def cmd_build(args):
    population = load_agg(args.population)
    pop_by_id = {p["id"]: p for p in population}
    pop_by_stratum, _ = draw_sample(population)
    if args.ids and args.ids != "none":
        with open(args.ids) as fh:
            fixed = json.load(fh)["clips"]
        stratum_of = {c["snippet_id"]: c["stratum"] for c in fixed}
        weight_of = {c["snippet_id"]: c["weight"] for c in fixed}
        expected_label = {c["snippet_id"]: c["stage3_overall"] for c in fixed}
    else:
        _, chosen = draw_sample(population)
        stratum_of = {i: name for name, ids in chosen.items() for i in ids}
        weight_of, expected_label = None, {}

    details = {}
    for path in sorted({f for pattern in args.details for f in glob.glob(pattern)}):
        for row in load_agg(path):
            details[row["id"]] = row

    drops, dropped_ids, label_changed, window_mismatch, records = Counter(), defaultdict(list), [], 0, []
    for sid in sorted(stratum_of):
        p, d = pop_by_id.get(sid), details.get(sid)
        reason = None
        if p is None:
            reason = "not_in_population (re-analyzed or filter changed)"
        elif d is None:
            reason = "no_details_row (missing Stage 1 response)"
        elif not d.get("flagged"):
            reason = "no_matching_flagged_snippet"
        elif not (d.get("clip_excerpt") or "").strip():
            reason = "empty_clip_excerpt"
        if reason:
            drops[reason] += 1
            dropped_ids[reason].append(sid)
            continue
        if abs(float(d["clip_start_s"]) - max(0.0, round(float(d["flag_start_s"])) - 90)) > 1:
            window_mismatch += 1
        rec = make_record(sid, p, d, stratum_of[sid])
        if sid in expected_label and expected_label[sid] != rec["label"]["stage3_overall"]:
            label_changed.append(sid)
        records.append(rec)

    kept = Counter(r["stratum"] for r in records)
    for r in records:
        if weight_of is not None:
            r["weight"] = weight_of[r["snippet_id"]]
        else:
            r["weight"] = round(len(pop_by_stratum[r["stratum"]]) / kept[r["stratum"]], 6)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "precheck_eval.jsonl"), "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(args.out, "ids.json"), "w") as fh:
        json.dump({"seed": SEED,
                   "note": "weight = stratum population / stratum sample; split = md5(snippet_id) parity",
                   "clips": [{"snippet_id": r["snippet_id"], "split": r["split"], "stratum": r["stratum"],
                              "weight": r["weight"], "stage3_overall": r["label"]["stage3_overall"]}
                             for r in records]}, fh, indent=0)

    rep = {"population": len(population), "selected": len(stratum_of), "kept": len(records), "drops": dict(drops),
           "dropped_ids": dropped_ids, "label_changed_vs_ids": label_changed, "window_mismatch": window_mismatch,
           "kept_by_stratum": dict(kept), "splits": dict(Counter(r["split"] for r in records))}
    pop_bands = Counter(band(stage3_overall(p)) for p in population)
    w_bands, s_bands = Counter(), Counter()
    for r in records:
        b = band(r["label"]["stage3_overall"])
        s_bands[b] += 1
        w_bands[b] += r["weight"]
    rep["bands"] = {b: {"population": pop_bands[b], "sample": s_bands[b], "weighted": round(w_bands[b], 1)}
                    for b in ["90+", "80-89", "40-79", "<40"]}
    lens = [len(r["input"]["stage1_transcript_excerpt"]) for r in records]
    if lens:
        rep["excerpt_chars"] = {"min": min(lens), "median": statistics.median(lens), "p95": pct(lens, 0.95),
                                "max": max(lens), "lt200": sum(v < 200 for v in lens)}
    with open(os.path.join(args.out, "build_report.json"), "w") as fh:
        json.dump(rep, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in rep.items() if k != "dropped_ids"}, indent=1, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render-sql", help="print details.sql for one page")
    r.add_argument("--prefixes", required=True, help=f"leading hex digits, one of {PAGES} or any comma list")
    a = sub.add_parser("sample", help="draw a fresh sample from a population result")
    a.add_argument("--population", required=True)
    a.add_argument("--out", required=True)
    b = sub.add_parser("build", help="write the JSONL from population and details results")
    b.add_argument("--population", required=True)
    b.add_argument("--details", nargs="+", required=True, help="files or glob patterns")
    b.add_argument("--out", required=True)
    b.add_argument("--ids", default=DEFAULT_IDS, help="ids.json to rebuild exactly; 'none' to sample again")
    args = ap.parse_args()
    {"render-sql": cmd_render_sql, "sample": cmd_sample, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    main()
