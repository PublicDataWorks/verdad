import os
import time

from openai import OpenAI

from news_ledger.feeds import enabled_feeds
from news_ledger.poller import poll_feeds
from processing_pipeline.supabase_utils import SupabaseClient
from utils import optional_flow

# The ledger only needs to be as fresh as a news cycle; hourly keeps the feeds' own caches happy.
POLL_INTERVAL_SECONDS = 3600


@optional_flow(name="News Ledger: Poller", log_prints=True)
def news_ledger_poller(repeat: bool = False):
    """Poll the configured wire/fact-checker feeds into `news_index` and embed the new rows."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise ValueError("OpenAI API key was not set!")
    openai_client = OpenAI(api_key=openai_key)

    supabase_client = SupabaseClient(supabase_url=os.getenv("SUPABASE_URL"), supabase_key=os.getenv("SUPABASE_KEY"))

    while True:
        feeds = enabled_feeds()
        poll_feeds(supabase_client, openai_client, feeds)

        # Stop the flow if we're not meant to repeat the process
        if not repeat:
            break

        print(f"Sleep for {POLL_INTERVAL_SECONDS} seconds before the next poll")
        time.sleep(POLL_INTERVAL_SECONDS)
