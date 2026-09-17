"""
Seed public.sources from config/stations.yaml; idempotent on (type, external_id).
Usage (repo root): python src/scripts/backfill_sources.py [--dry-run] [--with-youtube]
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from stations import load_stations

load_dotenv()

# Texas doc channels, seeded disabled until the poller lands
YOUTUBE_CHANNELS = [
    ("UCm8RLxPfpn7r6Nuu8lKnerQ", "VOZ Media", "Texas"),
    ("UCkpysxVhIQGZ9lNJJ8iNvIw", "Telemundo 39 Dallas", "Texas"),
    ("UCRE80_g2o9cF542U56GK3Rg", "Univision 41 San Antonio", "Texas"),
]


# bulk upsert sends missing keys as NULL, so every row must carry every column
ROW_DEFAULTS = {"location_state": None, "stream_url": None, "feed_urls": [], "enabled": True, "metadata": {}}


def youtube_feed_urls(channel_id):
    # UULF: uploads without Shorts/live. UULV: livestream recordings
    suffix = channel_id.removeprefix("UC")
    return [
        f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{suffix}",
        f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULV{suffix}",
    ]


def radio_rows():
    return [
        {
            "type": "radio",
            "external_id": s.code,
            "display_name": s.name,
            "location_state": s.state,
            "stream_url": s.url,
            "metadata": {"capture": "browser" if s.recorder == "generic" else "ffmpeg"},
        }
        for s in load_stations()
        if s.enabled
    ]


def youtube_rows():
    return [
        {
            "type": "youtube",
            "external_id": cid,
            "display_name": name,
            "location_state": state,
            "feed_urls": youtube_feed_urls(cid),
            "enabled": False,
        }
        for cid, name, state in YOUTUBE_CHANNELS
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-youtube", action="store_true")
    args = parser.parse_args()

    rows = [{**ROW_DEFAULTS, **r} for r in radio_rows() + (youtube_rows() if args.with_youtube else [])]
    keys = [(r["type"], r["external_id"]) for r in rows]
    if len(set(keys)) != len(keys):
        sys.exit("duplicate (type, external_id) in input")

    print(f"{len(rows)} rows ({sum(r['type'] == 'radio' for r in rows)} radio)")
    if args.dry_run:
        for r in rows:
            print(f"  {r['type']:8} {r['external_id']:24} {r['display_name']}")
        return

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    # ignore_duplicates keeps operator edits (enabled, poll interval) on rerun
    response = client.table("sources").upsert(rows, on_conflict="type,external_id", ignore_duplicates=True).execute()
    print(f"inserted {len(response.data)} new rows; {len(rows) - len(response.data)} already existed")


if __name__ == "__main__":
    main()
