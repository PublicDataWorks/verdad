#!/usr/bin/env python3
"""
Re-queue snippets for Stage 3 or Stage 4 by criteria.

Dry-run by default: prints the counts per criterion and the equivalent SQL (with --limit, the SQL lists the
selected ids). Pass --execute to flip the status in batches and write the selected ids to a JSON audit file.

Usage:
    python src/scripts/reprocess_snippets.py --fabricated-label --since 2026-03-23 --stage 3
    python src/scripts/reprocess_snippets.py --disliked --commented --min-confidence 95 --not-hidden --stage 4 --execute
    python src/scripts/reprocess_snippets.py --ids-file ids.txt --stage 3 --execute --audit-file requeued.json
    python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-09-15-heuristics --stage 3 --limit 500
    python src/scripts/reprocess_snippets.py --quarantine-batch hide-2026-09-15-heuristics \
        --quarantine-reason no_evidence_no_dated_source --stage 3 --limit 50
    python src/scripts/reprocess_snippets.py --error-keyerror --stage 3 --execute

Selection semantics: the "reason" criteria (--fabricated-label, --disliked, --commented, --ids-file,
--quarantine-batch, --error-keyerror) are OR-ed; the filters (--since, --min-confidence, --not-hidden, --limit) are
AND-ed on top of that set. Candidates are ordered newest recorded_at first (the order the Stage 3 poller uses), so
--limit takes the newest ones. Snippets currently in flight (status Processing or Reviewing) are always skipped so
a worker mid-run is never flipped underneath.

--quarantine-batch reads snippet_quarantine_log (batch = NAME, restored_at IS NULL), the table the 2026-09 cleanup
wrote (created by PR #81's cleanup_2026_09/02_create_snippet_quarantine_log.sql, not yet in this tree). The cleanup
hid those snippets through user_hide_snippets without changing snippets.status, so they are still 'Processed' here;
this script only re-queues them and never stamps restored_at or removes the hide row. Unhiding is a separate manual
step per batch once the new analysis is in. Do not combine --quarantine-batch with --not-hidden: every quarantined
snippet is hidden by construction. --quarantine-reason REASON (repeatable, only with --quarantine-batch) narrows
the selection to log rows whose reason column is one of the given values, so a batch can be re-queued one reason
at a time; the reason list is recorded in the audit file's selected_by entries and in the printed SQL.
--error-keyerror selects status = 'Error' with error_message starting 'KeyError:' (VER-363 backfill).
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from processing_pipeline.stage_3.models import FALSITY_TERMS, FALSITY_TERM_PATTERNS, mentions_falsity  # noqa: E402

load_dotenv()

BATCH_SIZE = 100  # ids go into the request URL as an `in.(...)` filter; 100 UUIDs stay well under URL limits
PAGE_SIZE = 1000
STAGE_TARGET_STATUS = {3: "New", 4: "Ready for review"}
# A snippet a worker is currently handling must not be flipped mid-run: Stage 3 writes its result and status at the
# end of the run and would clobber (or be clobbered by) the requeue.
IN_FLIGHT_STATUSES = ("Processing", "Reviewing")
REASON_FLAGS = ("fabricated_label", "disliked", "commented", "ids_file", "quarantine_batch", "error_keyerror")
KEYERROR_PREFIX = "KeyError:"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Re-queue snippets for Stage 3 or Stage 4 by criteria.")
    parser.add_argument(
        "--fabricated-label", action="store_true", help="snippets carrying a label that asserts fabrication"
    )
    parser.add_argument("--disliked", action="store_true", help="snippets with at least one dislike")
    parser.add_argument("--commented", action="store_true", help="snippets with at least one comment")
    parser.add_argument("--ids-file", help="file with snippet ids (one per line, or a JSON list)")
    parser.add_argument(
        "--quarantine-batch",
        action="append",
        metavar="NAME",
        help="snippets in snippet_quarantine_log with this batch and restored_at IS NULL (repeatable)",
    )
    parser.add_argument(
        "--quarantine-reason",
        action="append",
        metavar="REASON",
        help="with --quarantine-batch: only log rows whose reason is one of these (repeatable)",
    )
    parser.add_argument(
        "--error-keyerror",
        action="store_true",
        help=f"snippets with status 'Error' and error_message starting '{KEYERROR_PREFIX}' (VER-363 backfill)",
    )
    parser.add_argument("--since", type=date.fromisoformat, metavar="YYYY-MM-DD", help="recorded_at on/after this date")
    parser.add_argument("--min-confidence", type=int, metavar="N", help="confidence_scores.overall >= N")
    parser.add_argument("--not-hidden", action="store_true", help="exclude snippets present in user_hide_snippets")
    parser.add_argument("--limit", type=int, metavar="N", help="cap the number of snippets re-queued")
    parser.add_argument("--stage", type=int, choices=(3, 4), required=True, help="3 -> 'New', 4 -> 'Ready for review'")
    parser.add_argument("--execute", action="store_true", help="write the status change (default is dry-run)")
    parser.add_argument("--audit-file", help="JSON file for the selected ids (default: reprocess_<stage>_<utc>.json)")
    args = parser.parse_args(argv)
    if not any(getattr(args, flag) for flag in REASON_FLAGS):
        parser.error(
            "select at least one of --fabricated-label, --disliked, --commented, --ids-file, "
            "--quarantine-batch, --error-keyerror"
        )
    if args.quarantine_reason and not args.quarantine_batch:
        parser.error("--quarantine-reason only narrows --quarantine-batch; pass a batch name too")
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
    return mentions_falsity(" ".join(str(label.get(key) or "") for key in ("text", "text_spanish")))


def overall_confidence(snippet: dict):
    scores = snippet.get("confidence_scores") or {}
    value = scores.get("overall") if isinstance(scores, dict) else None
    return value if isinstance(value, (int, float)) else None


def recorded_at_key(snippet: dict):
    """Sort key for newest-first ordering; snippets without recorded_at sort last."""
    recorded = snippet.get("recorded_at") or ""
    if not recorded:
        return datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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
    """Union the reason sets, apply the filters, return (ids newest recorded_at first, counts by criterion)."""
    candidates = set().union(*reason_ids.values()) if reason_ids else set()
    counts = {reason: len(ids) for reason, ids in reason_ids.items()}
    counts["union"] = len(candidates)

    known = [snippets_by_id[sid] for sid in candidates if sid in snippets_by_id]
    known.sort(key=lambda snippet: (recorded_at_key(snippet), snippet["id"]), reverse=True)

    selected = []
    skipped_in_flight = 0
    for snippet in known:
        snippet_id = snippet["id"]
        if not passes_filters(snippet, since, min_confidence, hidden_ids):
            continue
        if snippet.get("status") in IN_FLIGHT_STATUSES:
            skipped_in_flight += 1
            continue
        selected.append(snippet_id)
    counts["skipped_in_flight"] = skipped_in_flight
    counts["after_filters"] = len(selected)
    if limit is not None:
        selected = selected[:limit]
    counts["selected"] = len(selected)
    return selected, counts


def quarantine_selector_name(reasons: list | None) -> str:
    """Key for the quarantine selector in the counts and the audit file; names the reason filter when one is set."""
    if not reasons:
        return "quarantine_batch"
    return "quarantine_batch[reason=" + ",".join(reasons) + "]"


def selectors_by_id(reason_ids: dict[str, set], selected: list) -> dict[str, list]:
    """Which selector(s) produced each selected id, for the audit file."""
    return {sid: sorted(reason for reason, ids in reason_ids.items() if sid in ids) for sid in selected}


def build_sql(args, target_status: str, selected: list | None = None) -> str:
    """SQL equivalent for the audit trail / manual runs; under --limit it targets the selected ids, not the criteria."""
    in_flight = "s.status NOT IN (" + ", ".join(f"'{status}'" for status in IN_FLIGHT_STATUSES) + ")"
    update = f"UPDATE snippets s\nSET status = '{target_status}', error_message = NULL\nWHERE "
    if args.limit is not None:
        ids = ", ".join(f"'{sid}'" for sid in selected or []) or "NULL"
        return f"{update}s.id IN ({ids})\n  AND {in_flight};"

    reasons = []
    if args.fabricated_label:
        # ILIKE cannot express the exclusions in FALSITY_TERM_PATTERNS ("made up of" is not fabrication), so the
        # audit SQL leaves those terms out; the script itself selects with mentions_falsity, which applies them.
        plain_terms = [t for t in FALSITY_TERMS if t not in FALSITY_TERM_PATTERNS]
        terms = " OR ".join(f"l.text ILIKE '%{t}%' OR l.text_spanish ILIKE '%{t}%'" for t in plain_terms)
        reasons.append(
            "s.id IN (SELECT sl.snippet FROM snippet_labels sl JOIN labels l ON l.id = sl.label WHERE " + terms + ")"
        )
    if args.disliked:
        reasons.append("s.id IN (SELECT snippet FROM user_like_snippets WHERE value = -1)")
    if args.commented:
        reasons.append("s.comment_count > 0")
    if args.ids_file:
        reasons.append(f"s.id IN (<ids from {args.ids_file}>)")
    if args.quarantine_batch:
        batches = ", ".join(f"'{name}'" for name in args.quarantine_batch)
        reason_filter = ""
        if args.quarantine_reason:
            reason_filter = " AND reason IN (" + ", ".join(f"'{r}'" for r in args.quarantine_reason) + ")"
        reasons.append(
            "s.id IN (SELECT snippet FROM snippet_quarantine_log WHERE batch IN (" + batches + ")"
            + reason_filter
            + " AND restored_at IS NULL)"
        )
    if args.error_keyerror:
        reasons.append(f"(s.status = 'Error' AND s.error_message LIKE '{KEYERROR_PREFIX}%')")

    filters = []
    if args.since:
        filters.append(f"s.recorded_at >= '{args.since.isoformat()}'")
    if args.min_confidence is not None:
        filters.append(f"(s.confidence_scores->>'overall')::INTEGER >= {args.min_confidence}")
    if args.not_hidden:
        filters.append("s.id NOT IN (SELECT snippet FROM user_hide_snippets)")
    filters.append(in_flight)

    where = "(" + " OR ".join(reasons) + ")\n  AND " + "\n  AND ".join(filters)
    return f"{update}{where};"


def chunked(items: list, size: int):
    for start in range(0, len(items), size):
        end = start + size
        yield items[start:end]


# --- Supabase access -----------------------------------------------------------------------------------------


def get_supabase_client():
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY must be set")
    return create_client(url, key)


def fetch_all(build_query, key: str = "id"):
    """Read every row of a query, PAGE_SIZE rows at a time, as keyset pages on ``key``.

    ``build_query`` must return a fresh query builder on each call (postgrest builders accumulate params) and
    must select ``key``. Offset paging skips or repeats rows when concurrent writes shift later pages and gets
    slower with depth; ``key > last`` over an indexed column does neither. A non-unique ``key`` may lose rows
    that share the boundary value, so only use one when callers need the distinct key values.
    """
    rows, last = [], None
    while True:
        query = build_query().order(key).limit(PAGE_SIZE)
        if last is not None:
            query = query.gt(key, last)
        page = query.execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        last = page[-1][key]


def fetch_fabricated_label_snippet_ids(client) -> set:
    labels = fetch_all(lambda: client.table("labels").select("id, text, text_spanish"))
    label_ids = [label["id"] for label in labels if label_matches_falsity(label)]
    ids = set()
    for batch in chunked(label_ids, BATCH_SIZE):
        rows = fetch_all(lambda batch=batch: client.table("snippet_labels").select("id, snippet").in_("label", batch))
        ids.update(row["snippet"] for row in rows)
    return ids


def fetch_disliked_snippet_ids(client) -> set:
    rows = fetch_all(lambda: client.table("user_like_snippets").select("id, snippet").eq("value", -1))
    return {row["snippet"] for row in rows}


def fetch_commented_snippet_ids(client) -> set:
    rows = fetch_all(lambda: client.table("snippets").select("id").gt("comment_count", 0))
    return {row["id"] for row in rows}


def fetch_quarantine_batch_snippet_ids(client, batches: list, reasons: list | None = None) -> set:
    """Snippets logged under any of the batches and not yet restored (restored_at IS NULL).

    With ``reasons``, only log rows whose reason is one of them count (a subset of the batch).
    """

    def build_query():
        query = client.table("snippet_quarantine_log").select("id, snippet").in_("batch", list(batches))
        if reasons:
            query = query.in_("reason", list(reasons))
        return query.is_("restored_at", "null")

    rows = fetch_all(build_query)
    return {row["snippet"] for row in rows}


def fetch_keyerror_snippet_ids(client, since: date | None = None) -> set:
    # --since goes into the query: the KeyError set is ~70k rows, too many to filter client-side.
    def build():
        query = client.table("snippets").select("id").eq("status", "Error").like("error_message", f"{KEYERROR_PREFIX}%")
        return query.gte("recorded_at", since.isoformat()) if since else query

    return {row["id"] for row in fetch_all(build)}


def fetch_hidden_snippet_ids(client) -> set:
    # user_hide_snippets has no id column; snippet repeats per user, which the set absorbs.
    rows = fetch_all(lambda: client.table("user_hide_snippets").select("snippet"), key="snippet")
    return {row["snippet"] for row in rows}


def fetch_snippets(client, ids: list) -> dict[str, dict]:
    snippets = {}
    columns = "id, status, recorded_at, confidence_scores"
    for batch in chunked(ids, BATCH_SIZE):
        rows = fetch_all(lambda batch=batch: client.table("snippets").select(columns).in_("id", batch))
        snippets.update({row["id"]: row for row in rows})
    return snippets


def requeue(client, ids: list, target_status: str):
    # A worker may have picked a snippet up since selection; the status guard keeps it out of the update.
    for batch in chunked(ids, BATCH_SIZE):
        rows = (
            client.table("snippets")
            .update({"status": target_status, "error_message": None})
            .in_("id", batch)
            .not_.in_("status", list(IN_FLIGHT_STATUSES))
            .execute()
            .data
            or []
        )
        print(f"  updated {len(rows)} of {len(batch)} snippets -> '{target_status}'")


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
    if args.quarantine_batch:
        reason_ids[quarantine_selector_name(args.quarantine_reason)] = fetch_quarantine_batch_snippet_ids(
            client, args.quarantine_batch, args.quarantine_reason
        )
    if args.error_keyerror:
        reason_ids["error_keyerror"] = fetch_keyerror_snippet_ids(client, args.since)

    candidate_ids = sorted(set().union(*reason_ids.values()))
    snippets_by_id = fetch_snippets(client, candidate_ids)
    hidden_ids = fetch_hidden_snippet_ids(client) if args.not_hidden else set()

    selected, counts = select_snippets(
        reason_ids, snippets_by_id, args.since, args.min_confidence, hidden_ids, args.limit
    )

    print("Counts by criterion:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    if counts["skipped_in_flight"]:
        statuses = " / ".join(IN_FLIGHT_STATUSES)
        print(f"  ({counts['skipped_in_flight']} skipped because their status is {statuses}; re-run once they finish)")
    print("\nEquivalent SQL:\n" + build_sql(args, target_status, selected))
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
                "selected_by": selectors_by_id(reason_ids, selected),
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
