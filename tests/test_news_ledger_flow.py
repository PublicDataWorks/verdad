"""The news ledger Prefect flow: client setup and loop semantics. No network, no real sleep."""

import pytest

from news_ledger import flows


@pytest.fixture
def patched(monkeypatch):
    calls = {"polls": 0, "sleeps": []}

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(flows, "OpenAI", lambda api_key: f"openai:{api_key}")
    monkeypatch.setattr(flows, "SupabaseClient", lambda supabase_url, supabase_key: "supabase")
    monkeypatch.setattr(flows, "enabled_feeds", lambda: ["feed"])
    monkeypatch.setattr(flows.time, "sleep", lambda seconds: calls["sleeps"].append(seconds))

    def poll(supabase_client, openai_client, feeds):
        calls["polls"] += 1
        calls["args"] = (supabase_client, openai_client, feeds)
        if calls["polls"] >= 2:
            raise StopIteration("enough")
        return {"items": 0}

    monkeypatch.setattr(flows, "poll_feeds", poll)
    return calls


def test_single_pass_polls_once_and_does_not_sleep(patched):
    flows.news_ledger_poller(repeat=False)

    assert patched["polls"] == 1
    assert patched["sleeps"] == []
    assert patched["args"] == ("supabase", "openai:test-key", ["feed"])


def test_repeat_sleeps_between_polls(patched):
    with pytest.raises(StopIteration):
        flows.news_ledger_poller(repeat=True)

    assert patched["polls"] == 2
    assert patched["sleeps"] == [flows.POLL_INTERVAL_SECONDS]


def test_missing_openai_key_is_reported_at_flow_start(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OpenAI API key"):
        flows.news_ledger_poller(repeat=False)
