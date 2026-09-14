#!/usr/bin/env python3
"""
Re-queue snippets for Stage 3 or Stage 4 by criteria.

Dry-run by default: prints the counts per criterion, the equivalent SQL, and the ids that would change.
Pass --execute to flip the status (in batches of 500) and write the selected ids to a JSON audit file.

Usage:
    python src/scripts/reprocess_snippets.py --fabricated-label --since 2026-03-23 --stage 3
    python src/scripts/reprocess_snippets.py --disliked --commented --min-confidence 95 --not-hidden --stage 4 --execute
    python src/scripts/reprocess_snippets.py --ids-file ids.txt --stage 3 --execute --audit-file requeued.json

Selection semantics: the "reason" criteria (--fabricated-label, --disliked, --commented, --ids-file) are OR-ed;
the filters (--since, --min-confidence, --not-hidden, --limit) are AND-ed on top of that set.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

BATCH_SIZE = 500
PAGE_SIZE = 1000
FALSITY_TERMS = (
    "fabricat",
    "fabricado",
    "ficticio",
    "fictional",
    "did not happen",
    "no ocurrió",
    "no existe",
    "does not exist",
    "invented",
    "inventado",
)
STAGE_TARGET_STATUS = {3: "New", 4: "Ready for review"}
REASON_FLAGS = ("fabricated_label", "disliked", "commented", "ids_file")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Re-queue snippets for Stage 3 or Stage 4 by criteria.")
    parser.add_argument(
        "--fabricated-label", action="store_true", help="snippets carrying a label that asserts fabrication"
    )
    parser.add_argument("--disliked", action="store_true", help="snippets with at least one dislike")
    parser.add_argument("--commented", action="store_true", help="snippets with at least one comment")
    parser.add_argument("--ids-file", help="file with snippet ids (one per line, or a JSON list)")
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD", help="recorded_at on/after this date")
    parser.add_argument("--min-confidence", type=int, metavar="N", help="confidence_scores.overall >= N")
    parser.add_argument("--not-hidden", action="store_true", help="exclude snippets present in user_hide_snippets")
    parser.add_argument("--limit", type=int, metavar="N", help="cap the number of snippets re-queued")
    parser.add_argument("--stage", type=int, choices=(3, 4), required=True, help="3 -> 'New', 4 -> 'Ready for review'")
    parser.add_argument("--execute", action="store_true", help="write the status change (default is dry-run)")
    parser.add_argument("--audit-file", help="JSON file for the selected ids (default: reprocess_<stage>_<utc>.json)")
    args = parser.parse_args(argv)
    if not any(getattr(args, flag) for flag in REASON_FLAGS):
        parser.error("select at least one of --fabricated-label, --disliked, --commented, --ids-file")
    return args


# --- pure selection logic -----------------------------------------------------------------------------------


def parse_ids_file(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return [str(value) for value in json.loads(text)]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def label_matches_falsity(label: dict) -> bool:
    haystack = " ".join(str(label.get(key) or "") for key in ("text", "text_spanish")).lower()
    return any(term in haystack for term in FALSITY_TERMS)


def overall_confidence(snippet: dict):
    scores = snippet.get("confidence_scores") or {}
    value = scores.get("overall") if isinstance(scores, dict) else None
    return value if isinstance(value, (int, float)) else None


def passes_filters(snippet: dict, since: date | None, min_confidence: int | None, hidden_ids: set) -> bool:
    if since is not None:
        recorded = snippet.get("recorded_at") or ""
        if not recorded or datetime.fromisoformat(recorded.replace("Z", "+00:00")).date() < since:
            return False
    if min_confidence is not None:
        overall = overall_confidence(snippet)
        if overall is None or overall < min_confidence:
            return False
    if snippet.get("id") in hidden_ids:
        return False
    return True


def select_snippets(
    reason_ids: dict[str, set], snippets_by_id: dict[str, dict], since, min_confidence, hidden_ids, limit
):
    """Union the reason sets, apply the filters, return (ordered ids, counts by criterion)."""
    candidates = set().union(*reason_ids.values()) if reason_ids else set()
    counts = {reason: len(ids) for reason, ids in reason_ids.items()}
    counts["union"] = len(candidates)

    selected = []
    for snippet_id in sorted(candidates):
        snippet = snippets_by_id.get(snippet_id)
        if snippet is None:
            continue
        if passes_filters(snippet, since, min_confidence, hidden_ids):
            selected.append(snippet_id)
    counts["after_filters"] = len(selected)
    if limit is not None:
        selected = selected[:limit]
    counts["selected"] = len(selected)
    return selected, counts


def build_sql(args, target_status: str) -> str:
    """The SQL equivalent of what the script does, for the audit trail / manual runs."""
    reasons = []
    if args.fabricated_label:
        terms = " OR ".join(f"l.text ILIKE '%{t}%' OR l.text_spanish ILIKE '%{t}%'" for t in FALSITY_TERMS)
        reasons.append(
            "s.id IN (SELECT sl.snippet FROM snippet_labels sl JOIN labels l ON l.id = sl.label WHERE " + terms + ")"
        )
    if args.disliked:
        reasons.append("s.id IN (SELECT snippet FROM user_like_snippets WHERE value = -1)")
    if args.commented:
        reasons.append("s.comment_count > 0")
    if args.ids_file:
        reasons.append(f"s.id IN (<ids from {args.ids_file}>)")

    filters = []
    if args.since:
        filters.append(f"s.recorded_at >= '{args.since.isoformat()}'")
    if args.min_confidence is not None:
        filters.append(f"(s.confidence_scores->>'overall')::INTEGER >= {args.min_confidence}")
    if args.not_hidden:
        filters.append("s.id NOT IN (SELECT snippet FROM user_hide_snippets)")

    where = "(" + " OR ".join(reasons) + ")"
    if filters:
        where += "\n  AND " + "\n  AND ".join(filters)
    sql = f"UPDATE snippets s\nSET status = '{target_status}', error_message = NULL\nWHERE {where}"
    if args.limit is not None:
        sql += f"\n  -- limited to the first {args.limit} ids by the script"
    return sql + ";"


def chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


# --- Supabase access -----------------------------------------------------------------------------------------


def get_supabase_client():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def fetch_all(query):
    rows = []
    start = 0
    while True:
        page = query.range(start, start + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def fetch_fabricated_label_snippet_ids(client) -> set:
    labels = fetch_all(client.table("labels").select("id, text, text_spanish"))
    label_ids = [label["id"] for label in labels if label_matches_falsity(label)]
    ids = set()
    for batch in chunked(label_ids, BATCH_SIZE):
        rows = fetch_all(client.table("snippet_labels").select("snippet").in_("label", batch))
        ids.update(row["snippet"] for row in rows)
    return ids


def fetch_disliked_snippet_ids(client) -> set:
    rows = fetch_all(client.table("user_like_snippets").select("snippet").eq("value", -1))
    return {row["snippet"] for row in rows}


def fetch_commented_snippet_ids(client) -> set:
    rows = fetch_all(client.table("snippets").select("id").gt("comment_count", 0))
    return {row["id"] for row in rows}


def fetch_hidden_snippet_ids(client) -> set:
    rows = fetch_all(client.table("user_hide_snippets").select("snippet"))
    return {row["snippet"] for row in rows}


def fetch_snippets(client, ids: list) -> dict[str, dict]:
    snippets = {}
    for batch in chunked(ids, BATCH_SIZE):
        rows = fetch_all(client.table("snippets").select("id, status, recorded_at, confidence_scores").in_("id", batch))
        snippets.update({row["id"]: row for row in rows})
    return snippets


def requeue(client, ids: list, target_status: str):
    for batch in chunked(ids, BATCH_SIZE):
        client.table("snippets").update({"status": target_status, "error_message": None}).in_("id", batch).execute()
        print(f"  updated {len(batch)} snippets -> '{target_status}'")


def main(argv=None):
    args = parse_args(argv)
    target_status = STAGE_TARGET_STATUS[args.stage]
    client = get_supabase_client()

    reason_ids = {}
    if args.fabricated_label:
        reason_ids["fabricated_label"] = fetch_fabricated_label_snippet_ids(client)
    if args.disliked:
        reason_ids["disliked"] = fetch_disliked_snippet_ids(client)
    if args.commented:
        reason_ids["commented"] = fetch_commented_snippet_ids(client)
    if args.ids_file:
        with open(args.ids_file, encoding="utf-8") as f:
            reason_ids["ids_file"] = set(parse_ids_file(f.read()))

    candidate_ids = sorted(set().union(*reason_ids.values()))
    snippets_by_id = fetch_snippets(client, candidate_ids)
    hidden_ids = fetch_hidden_snippet_ids(client) if args.not_hidden else set()

    selected, counts = select_snippets(
        reason_ids, snippets_by_id, args.since, args.min_confidence, hidden_ids, args.limit
    )

    print("Counts by criterion:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print("\nEquivalent SQL:\n" + build_sql(args, target_status))
    print(f"\n{len(selected)} snippet(s) would be set to '{target_status}'")

    if not args.execute:
        print("\nDry run. Re-run with --execute to apply.")
        return 0
    if not selected:
        print("Nothing to do.")
        return 0

    audit_file = args.audit_file or f"reprocess_stage{args.stage}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    with open(audit_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "target_status": target_status,
                "criteria": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in vars(args).items()},
                "counts": counts,
                "previous_status": {sid: snippets_by_id[sid].get("status") for sid in selected},
                "snippet_ids": selected,
            },
            f,
            indent=2,
        )
    print(f"Wrote audit file {audit_file}")

    requeue(client, selected, target_status)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
