"""Integrity and leakage checks on a built precheck_eval.jsonl.

  python3 -I check_leakage.py DIR/precheck_eval.jsonl [--stage3 SAVED_RESULT]

--stage3 takes a saved result of a query returning jsonb_agg({id, s3_transcription}) for some clips, and checks that
no Stage 3 transcription appears verbatim in `input`. Exits 1 when a check fails.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_result import load_agg  # noqa: E402

ALLOWED_INPUT = {"stage1_explanation", "stage1_keywords", "stage1_categories", "stage1_transcript_excerpt",
                 "start_time", "end_time", "duration_s", "stage1_transcriptor", "stage1_language", "stage1_extra"}
ALLOWED_EXTRA = {"flagged_transcription", "core_excerpt", "clip_start_s", "clip_end_s", "clip_duration_s",
                 "n_flagged_in_recording", "flagged_index", "recording_words_total",
                 "stage1_language_heuristic_share", "detection_prompt_version_id", "transcription_prompt_version_id",
                 "audio_recorded_at", "other_flagged_fields"}
# Stage 3 stores explanation and categories as {"english": ..., "spanish": ...}; Stage 1 uses plain strings.
FORBIDDEN = ['"english":', '"spanish":', "confidence_scores", "primary_language", "political_leaning",
             "emotional_tone", "analyzed_by", "gemini-3"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl")
    ap.add_argument("--stage3")
    args = ap.parse_args()
    with open(args.jsonl, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    failures = []
    ids = [r["snippet_id"] for r in rows]
    if len(ids) != len(set(ids)):
        failures.append("duplicate snippet ids")
    if any(r["label"].get("stage3_overall") is None for r in rows):
        failures.append("null label.stage3_overall")
    for r in rows:
        extra_keys = set(r["input"]) - ALLOWED_INPUT
        extra_keys |= set(r["input"].get("stage1_extra", {})) - ALLOWED_EXTRA
        if extra_keys:
            failures.append(f"{r['snippet_id']}: unexpected input keys {sorted(extra_keys)}")
        if r["input"]["stage1_extra"].get("other_flagged_fields"):
            failures.append(f"{r['snippet_id']}: unreviewed Stage 1 fields in other_flagged_fields")
        structured = {k: v for k, v in r["input"].items() if k != "stage1_transcript_excerpt" and k != "stage1_extra"}
        text = json.dumps(structured, ensure_ascii=False)
        for token in FORBIDDEN:
            if token in text:
                failures.append(f"{r['snippet_id']}: {token!r} in input")
    if args.stage3:
        by_id = {r["snippet_id"]: r for r in rows}
        for item in load_agg(args.stage3):
            s3 = (item.get("s3_transcription") or "").strip()
            r = by_id.get(item["id"])
            if r and len(s3) > 40 and s3 in json.dumps(r["input"], ensure_ascii=False):
                failures.append(f"{item['id']}: Stage 3 transcription found in input")
    print(f"rows {len(rows)}, unique ids {len(set(ids))}, failures {len(failures)}")
    for line in failures[:50]:
        print("  " + line)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
