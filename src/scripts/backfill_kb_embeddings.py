"""Backfill embeddings for KB entries that don't have them yet.

Usage:
    python -m scripts.backfill_kb_embeddings

Requires SUPABASE_URL, SUPABASE_KEY, and OPENAI_API_KEY env vars.
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI
from tiktoken import encoding_for_model

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from processing_pipeline.supabase_utils import SupabaseClient


def generate_kb_document(
    fact: str, related_claim: str | None = None, categories: list[str] | None = None
) -> str:
    parts = [f"Fact: {fact}"]
    if related_claim:
        parts.append(f"Related claim: {related_claim}")
    if categories:
        parts.append(f"Categories: {', '.join(categories)}")
    return "\n\n".join(parts)


def main():
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not all([supabase_url, supabase_key, openai_api_key]):
        print("Missing required env vars: SUPABASE_URL, SUPABASE_KEY, OPENAI_API_KEY")
        sys.exit(1)

    client = SupabaseClient(supabase_url=supabase_url, supabase_key=supabase_key)
    openai_client = OpenAI(api_key=openai_api_key)
    encoding = encoding_for_model("text-embedding-3-large")

    # Find KB entries without embeddings
    entries = (
        client.client.table("kb_entries")
        .select("id, fact, related_claim, disinformation_categories")
        .eq("status", "active")
        .execute()
    )

    existing_embeddings = (
        client.client.table("kb_entry_embeddings").select("kb_entry").execute()
    )
    embedded_ids = {e["kb_entry"] for e in existing_embeddings.data}

    missing = [e for e in entries.data if e["id"] not in embedded_ids]
    print(
        f"Found {len(missing)} KB entries without embeddings (out of {len(entries.data)} active)"
    )

    if not missing:
        print("Nothing to backfill.")
        return

    for i, entry in enumerate(missing):
        document = generate_kb_document(
            entry["fact"],
            entry.get("related_claim"),
            entry.get("disinformation_categories"),
        )

        response = openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=document,
        )
        embedding = response.data[0].embedding
        token_count = len(encoding.encode(document))

        client.upsert_kb_entry_embedding(
            kb_entry_id=entry["id"],
            embedded_document=document,
            document_token_count=token_count,
            embedding=embedding,
            model_name="text-embedding-3-large",
        )

        print(f"  [{i + 1}/{len(missing)}] Embedded: {entry['fact'][:80]}...")

    print(f"\nDone! Backfilled {len(missing)} embeddings.")


if __name__ == "__main__":
    main()
