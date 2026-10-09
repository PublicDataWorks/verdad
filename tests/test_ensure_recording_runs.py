"""Tests for src/scripts/ensure_recording_runs.py (recording watchdog, VER-421). No network: the Prefect
client is a fake that records every write."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from prefect.client.schemas.objects import StateType
from prefect.exceptions import ObjectNotFound

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import ensure_recording_runs as ere  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
MAX = "Audio Recording: Max Recorder"


def ago(minutes):
    return NOW - timedelta(minutes=minutes)


def make_run(state_type, *, deployment_id=None, created=None, start_time=None, state_since=None, name=None):
    created = created or ago(5)
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name or f"run-{state_type.value.lower()}",
        deployment_id=deployment_id,
        state_type=state_type,
        state=SimpleNamespace(name=state_type.value.title(), timestamp=state_since or created),
        created=created,
        start_time=start_time,
    )


class FakeClient:
    def __init__(self, deployments=None, runs=None, task_starts=None, health_error=None):
        self.deployments = deployments or {}
        self.runs = runs or []
        self.task_starts = task_starts or {}
        self.health_error = health_error
        self.state_writes = []
        self.created = []
        self.read_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def api_healthcheck(self):
        return self.health_error

    async def read_deployment_by_name(self, name):
        if name not in self.deployments:
            raise ObjectNotFound(http_exc=Exception("404"))
        return SimpleNamespace(id=self.deployments[name], name=name)

    async def read_flow_runs(self, *, flow_run_filter, sort=None, limit=None, offset=0):
        assert limit is not None and limit <= 200
        self.read_calls.append((limit, offset))
        states = set(flow_run_filter.state.type.any_)
        dep = flow_run_filter.deployment_id.any_ if flow_run_filter.deployment_id else None
        matching = [r for r in self.runs if r.state_type in states and (dep is None or r.deployment_id in dep)]
        return matching[offset : offset + limit]

    async def read_task_runs(self, *, flow_run_filter, sort=None, limit=None):
        run_id = flow_run_filter.id.any_[0]
        start = self.task_starts.get(run_id)
        return [] if start is None else [SimpleNamespace(start_time=start, expected_start_time=start)]

    async def set_flow_run_state(self, run_id, state, force=False):
        self.state_writes.append((run_id, state.type, state.message, force))
        for r in self.runs:
            if r.id == run_id:
                r.state_type = state.type

    async def create_flow_run_from_deployment(self, deployment_id):
        self.created.append(deployment_id)
        return SimpleNamespace(id=uuid.uuid4(), name="new-run")


@pytest.fixture
def setup(monkeypatch):
    def _setup(client, targets=(f"{MAX}/WAAA",)):
        monkeypatch.setattr(ere, "get_client", lambda: client)
        monkeypatch.setattr(ere, "_now", lambda: NOW)
        monkeypatch.setattr(ere.stations, "prefect_run_targets", lambda: list(targets))
        return client

    return _setup


def dep_id():
    return uuid.uuid4()


def test_healthy_running_run_by_task_activity(setup):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(300), start_time=ago(300))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run], task_starts={run.id: ago(12)}))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.state_writes == []
    assert client.created == []


def test_recently_started_running_run_is_healthy_without_task_lookup(setup):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, start_time=ago(3))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.state_writes == [] and client.created == []


def test_zombie_running_run_is_crashed_and_replaced(setup, capsys):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(240), start_time=ago(240))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run], task_starts={run.id: ago(229)}))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.state_writes == [(run.id, StateType.CRASHED, "watchdog: no task activity for 229 min", True)]
    assert client.created == [d]
    out = capsys.readouterr().out
    assert "checked=1 healthy=0 started=1 zombies_crashed=1 stale_cancels_closed=0" in out


def test_zombie_without_any_task_runs_uses_start_age(setup):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(90), start_time=ago(90))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes[0][2] == "watchdog: no task activity for 90 min"
    assert client.created == [d]


def test_recent_scheduled_run_means_no_action(setup):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [make_run(StateType.SCHEDULED, deployment_id=d, created=ago(2))]))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.state_writes == [] and client.created == []


def test_old_late_run_warns_but_does_not_pile_on(setup, capsys):
    d = dep_id()
    late = make_run(StateType.SCHEDULED, deployment_id=d, created=ago(120))
    late.state.name = "Late"
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [late]))
    ere.main(["--codes", "WAAA"])
    assert client.created == []
    assert "WARNING Late run" in capsys.readouterr().out


def test_stale_cancelling_closed_and_new_run_created(setup):
    d = dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=d, created=ago(400), state_since=ago(30))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [(stale.id, StateType.CANCELLED, "watchdog: stale cancellation", True)]
    assert client.created == [d]


def test_recent_cancelling_defers_new_run(setup, capsys):
    d = dep_id()
    fresh = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(2))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [fresh]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [] and client.created == []
    assert "deferred=1" in capsys.readouterr().out


def test_no_runs_at_all_starts_one(setup):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))
    ere.main(["--codes", "WAAA"])
    assert client.created == [d]


def test_dry_run_writes_nothing(setup, capsys):
    d = dep_id()
    zombie = make_run(StateType.RUNNING, deployment_id=d, created=ago(240), start_time=ago(240))
    stale = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(60))
    other = make_run(StateType.CANCELLING, deployment_id=dep_id(), state_since=ago(60))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [zombie, stale, other]))
    assert ere.main(["--dry-run"]) == 0
    assert client.state_writes == [] and client.created == []
    out = capsys.readouterr().out
    assert "[dry-run] would create a new flow run" in out
    assert "[dry-run] Summary:" in out
    # The global sweep "closes" both stale cancellations once; the per-station pass does not recount.
    assert "started=1 zombies_crashed=1 stale_cancels_closed=2" in out


def test_missing_deployment_is_skipped(setup, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WBBB": d}, []), targets=(f"{MAX}/WAAA", f"{MAX}/WBBB"))
    assert ere.main(["--codes", "WAAA", "WBBB"]) == 0
    assert client.created == [d]
    out = capsys.readouterr().out
    assert "deployment not found" in out
    assert "checked=2" in out and "missing=1" in out


def test_unknown_code_is_reported(setup, capsys):
    client = setup(FakeClient({}, []))
    ere.main(["--codes", "NOPE"])
    assert client.created == []
    assert "NOPE: not an enabled station" in capsys.readouterr().out


def test_global_sweep_paginates_over_200(setup):
    stale = [make_run(StateType.CANCELLING, deployment_id=dep_id(), state_since=ago(600)) for _ in range(450)]
    fresh = [make_run(StateType.CANCELLING, deployment_id=dep_id(), state_since=ago(1)) for _ in range(5)]
    # Fake reads are by offset over a list that the writes do not shrink (state_type changes only
    # filter later reads), so all pages are read before any write.
    client = setup(FakeClient({}, stale + fresh), targets=())
    assert ere.main(["--close-stale-cancelling"]) == 0
    assert [c[1] for c in client.read_calls] == [0, 200, 400]
    assert len(client.state_writes) == 450
    assert {w[1] for w in client.state_writes} == {StateType.CANCELLED}
    assert {w[0] for w in client.state_writes} == {r.id for r in stale}


def test_normal_run_includes_global_sweep_but_codes_run_does_not(setup):
    other = make_run(StateType.CANCELLING, deployment_id=dep_id(), state_since=ago(60))
    d = dep_id()
    healthy = make_run(StateType.SCHEDULED, deployment_id=d)
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [other, healthy]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == []
    ere.main([])
    assert [w[0] for w in client.state_writes] == [other.id]


def test_per_station_error_is_logged_and_does_not_fail(setup, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def boom(deployment_id):
        raise RuntimeError("409 conflict")

    client.create_flow_run_from_deployment = boom
    assert ere.main(["--codes", "WAAA"]) == 0
    assert "errors=1" in capsys.readouterr().out


def test_failed_state_write_is_not_counted(setup, capsys):
    d = dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(60))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale]))

    async def reject(run_id, state, force=False):
        raise RuntimeError("rejected")

    client.set_flow_run_state = reject
    assert ere.main(["--close-stale-cancelling"]) == 0
    out = capsys.readouterr().out
    assert "stale_cancels_closed=0" in out and "errors=1" in out


def test_unreachable_api_exits_non_zero(setup):
    setup(FakeClient(health_error=httpx.ConnectError("refused")))
    assert ere.main([]) == 1


def test_transport_error_mid_run_exits_non_zero(setup):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def drop(name):
        raise httpx.ConnectError("connection reset")

    client.read_deployment_by_name = drop
    assert ere.main(["--codes", "WAAA"]) == 1


def test_naive_timestamps_are_treated_as_utc():
    assert ere._age_minutes(datetime(2026, 10, 9, 11, 30), NOW) == 30
    assert ere._age_minutes(None, NOW) is None


def test_targets_come_from_the_station_list():
    targets = ere.select_targets(None)
    assert targets == ere.stations.prefect_run_targets()
    assert all("/" in t for t in targets)
