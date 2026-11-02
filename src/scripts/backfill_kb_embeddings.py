"""Backfill embeddings for KB entries that don't have them yet.

Usage:
    python -m scripts.backfill_kb_embeddings [--dry-run] [--limit N]

Requires SUPABASE_URL, SUPABASE_KEY, and OPENAI_API_KEY env vars.
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI
from tiktoken import encoding_for_model

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing_pipeline.processing_utils import normalize_embedding
from processing_pipeline.supabase_utils import SupabaseClient

EMBEDDING_MODEL = "text-embedding-3-large"
PAGE_SIZE = 1000


def fetch_all(query_builder_factory, page_size=PAGE_SIZE):
    """Read every row of a PostgREST select, one `page_size` page at a time.

    VER-377: PostgREST caps an unranged select at 1,000 rows, so the unpaged version of this
    script saw only the first 1,000 of ~11,300 embedding rows and treated ~6,000 already-embedded
    entries as missing. `query_builder_factory` must return a *fresh* builder on each call, since
    `.range()` is applied per page.
    """
    rows = []
    offset = 0
    while True:
        page = query_builder_factory().range(offset, offset + page_size - 1).execute()
        batch = page.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        offset += page_size


def generate_kb_document(fact: str, related_claim: str | None = None, categories: list[str] | None = None) -> str:
    parts = [f"Fact: {fact}"]
    if related_claim:
        parts.append(f"Related claim: {related_claim}")
    if categories:
        parts.append(f"Categories: {', '.join(categories)}")
    return "\n\n".join(parts)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Backfill embeddings for active KB entries that lack them.")
    parser.add_argument("--dry-run", action="store_true", help="List the missing entries and exit without embedding.")
    parser.add_argument("--limit", type=int, default=None, help="Embed at most N missing entries.")
    return parser.parse_args(argv)


def find_missing_entries(client):
    """Return (active entries, embedded kb_entry ids, entries without an embedding)."""
    entries = fetch_all(
        lambda: (
            client.client.table("kb_entries")
            .select("id, fact, related_claim, disinformation_categories")
            .eq("status", "active")
        )
    )
    existing_embeddings = fetch_all(lambda: client.client.table("kb_entry_embeddings").select("kb_entry"))
    embedded_ids = {e["kb_entry"] for e in existing_embeddings}
    missing = [e for e in entries if e["id"] not in embedded_ids]
    return entries, embedded_ids, missing


def main(argv=None):
    args = parse_args(argv)
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not all([supabase_url, supabase_key]) or not (openai_api_key or args.dry_run):
        print("Missing required env vars: SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY")
        sys.exit(1)

    client = SupabaseClient(supabase_url=supabase_url, supabase_key=supabase_key)

    entries, embedded_ids, missing = find_missing_entries(client)
    print(f"Active kb_entries:   {len(entries)}")
    print(f"Existing embeddings: {len(embedded_ids)}")
    print(f"Missing embeddings:  {len(missing)}")

    if not missing:
        print("Nothing to backfill.")
        return

    if args.dry_run:
        print("\nDry run; nothing will be embedded or written:")
        for entry in missing:
            print(f"  {entry['id']}  {entry['fact'][:80]}")
        return

    if args.limit is not None and args.limit < len(missing):
        missing = missing[: args.limit]
        print(f"Limiting this run to {len(missing)} entries (--limit).")

    openai_client = OpenAI(api_key=openai_api_key)
    encoding = encoding_for_model(EMBEDDING_MODEL)

    for i, entry in enumerate(missing):
        document = generate_kb_document(
            entry["fact"],
            entry.get("related_claim"),
            entry.get("disinformation_categories"),
        )

        response = openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=document,
        )
        embedding = normalize_embedding(response.data[0].embedding)
        token_count = len(encoding.encode(document))

        client.upsert_kb_entry_embedding(
            kb_entry_id=entry["id"],
            embedded_document=document,
            document_token_count=token_count,
            embedding=embedding,
            model_name=EMBEDDING_MODEL,
        )

        print(f"  [{i + 1}/{len(missing)}] Embedded: {entry['fact'][:80]}...")

    print(f"\nDone! Backfilled {len(missing)} embeddings.")


if __name__ == "__main__":
    main()
