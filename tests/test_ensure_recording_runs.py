"""Tests for src/scripts/ensure_recording_runs.py (recording watchdog, VER-421). No network: the Prefect
client is a fake that records every write and answers state changes with real OrchestrationResult objects,
and sentry_sdk is a MagicMock (conftest sets a dummy SENTRY_DSN for the whole suite)."""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from prefect.client.schemas.objects import StateType
from prefect.client.schemas.responses import (
    OrchestrationResult,
    SetStateStatus,
    StateAcceptDetails,
    StateRejectDetails,
)
from prefect.exceptions import ObjectNotFound, PrefectHTTPStatusError
from prefect.states import State

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


def http_500():
    request = httpx.Request("POST", "https://prefect.example/api/flow_runs/filter")
    response = httpx.Response(500, request=request, json={"detail": "Internal Server Error"})
    return PrefectHTTPStatusError.from_httpx_error(httpx.HTTPStatusError("500", request=request, response=response))


class FakeClient:
    def __init__(self, deployments=None, runs=None, task_starts=None, health_error=None, reject_ids=()):
        self.deployments = deployments or {}
        self.runs = runs or []
        self.task_starts = task_starts or {}
        self.health_error = health_error
        self.reject_ids = set(reject_ids)
        self.state_writes = []
        self.created = []
        self.read_calls = []
        self.now = NOW

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
        run = next((r for r in self.runs if r.id == run_id), None)
        if run_id in self.reject_ids:
            current = State(type=run.state_type) if run else None
            return OrchestrationResult(
                state=current,
                status=SetStateStatus.REJECT,
                details=StateRejectDetails(reason="Cannot transition flows that are cancelling to that state."),
            )
        self.state_writes.append((run_id, state.type, state.message, force))
        if run is not None:
            run.state_type = state.type
            run.state = SimpleNamespace(name=state.name, timestamp=self.now)
        return OrchestrationResult(state=state, status=SetStateStatus.ACCEPT, details=StateAcceptDetails())

    async def create_flow_run_from_deployment(self, deployment_id):
        self.created.append(deployment_id)
        return SimpleNamespace(id=uuid.uuid4(), name="new-run")


@pytest.fixture(autouse=True)
def sentry(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ere, "sentry_sdk", mock)
    return mock


@pytest.fixture(autouse=True)
def lock_file(tmp_path, monkeypatch):
    path = tmp_path / "verdad-recording.lock"
    monkeypatch.setenv("RECORDING_LOCK_FILE", str(path))
    return path


@pytest.fixture(autouse=True)
def no_fly(monkeypatch):
    """No test reaches real flyctl: the machine check is off unless a test sets FLY_MACHINE_IDS and fakes `_fly`."""
    monkeypatch.delenv("FLY_MACHINE_IDS", raising=False)

    def refuse(*args):
        raise AssertionError(f"unexpected flyctl call: {args}")

    monkeypatch.setattr(ere, "_fly", refuse)


@pytest.fixture
def setup(monkeypatch):
    def _setup(client, targets=(f"{MAX}/WAAA",), now=NOW):
        monkeypatch.setattr(ere, "get_client", lambda: client)
        monkeypatch.setattr(ere, "_now", lambda: now)
        monkeypatch.setattr(ere.stations, "prefect_run_targets", lambda: list(targets))
        return client

    return _setup


def dep_id():
    return uuid.uuid4()


# --- Running runs --------------------------------------------------------------------------------------------


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


def test_zombie_is_set_to_cancelling_and_not_replaced_in_the_same_tick(setup, capsys):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(240), start_time=ago(240))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run], task_starts={run.id: ago(229)}))
    assert ere.main(["--codes", "WAAA"]) == 0
    # Not forced: a live runner that sees Cancelling kills the process, so a misjudged run cannot keep recording.
    assert client.state_writes == [(run.id, StateType.CANCELLING, "watchdog: no task activity for 229 min", False)]
    assert client.created == []
    out = capsys.readouterr().out
    assert "checked=1 healthy=0 started=0 zombies_cancelled=1" in out
    assert "deferred=1" in out


def test_zombie_recovery_takes_two_ticks(setup, monkeypatch):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(240), start_time=ago(240))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    ere.main(["--codes", "WAAA"])
    assert client.created == []
    # Next tick, 15 min later: the runner never confirmed, so the cancellation is stale; close it and replace.
    later = NOW + timedelta(minutes=15)
    monkeypatch.setattr(ere, "_now", lambda: later)
    client.now = later
    ere.main(["--codes", "WAAA"])
    assert [w[1] for w in client.state_writes] == [StateType.CANCELLING, StateType.CANCELLED]
    assert client.state_writes[1][3] is True
    assert client.created == [d]


def test_zombie_without_any_task_runs_uses_start_age(setup):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(90), start_time=ago(90))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes[0][1:3] == (StateType.CANCELLING, "watchdog: no task activity for 90 min")
    assert client.created == []


def test_healthy_and_zombie_on_one_deployment(setup, capsys):
    d = dep_id()
    healthy = make_run(StateType.RUNNING, deployment_id=d, created=ago(300), start_time=ago(300), name="healthy")
    zombie = make_run(StateType.RUNNING, deployment_id=d, created=ago(600), start_time=ago(600), name="zombie")
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [healthy, zombie], task_starts={healthy.id: ago(5)}))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert [(w[0], w[1]) for w in client.state_writes] == [(zombie.id, StateType.CANCELLING)]
    assert client.created == []
    out = capsys.readouterr().out
    assert "healthy=1" in out and "zombies_cancelled=1" in out and "deferred=0" in out


def test_running_run_with_no_start_time_falls_back_to_state_timestamp(setup):
    d = dep_id()
    fresh = make_run(StateType.RUNNING, deployment_id=d, created=ago(300), state_since=ago(10))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [fresh]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [] and client.created == []

    stale = make_run(StateType.RUNNING, deployment_id=d, created=ago(300), state_since=ago(100))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [(stale.id, StateType.CANCELLING, "watchdog: no task activity for 100 min", False)]


@pytest.mark.parametrize("idle, zombie", [(44, False), (45, True)])
def test_running_idle_boundary_is_45_minutes(setup, idle, zombie):
    d = dep_id()
    run = make_run(StateType.RUNNING, deployment_id=d, created=ago(300), start_time=ago(300))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run], task_starts={run.id: ago(idle)}))
    ere.main(["--codes", "WAAA"])
    assert bool(client.state_writes) is zombie


# --- Scheduled and Pending runs ------------------------------------------------------------------------------


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
    assert client.created == [] and client.state_writes == []
    assert "WARNING Late run" in capsys.readouterr().out


def test_old_late_run_is_a_failure_that_reaches_sentry(setup, sentry):
    d = dep_id()
    late = make_run(StateType.SCHEDULED, deployment_id=d, created=ago(31))
    late.state.name = "Late"
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [late]))
    assert ere.main([]) == ere.EXIT_ERRORS
    assert client.created == [] and client.state_writes == []
    [call] = sentry.capture_event.call_args_list
    assert "1 runs stuck in Scheduled" in call.args[0]["message"]
    assert "stuck_scheduled=1" in call.args[0]["extra"]["summary"]
    assert sentry.crons.monitor.return_value.__exit__.call_args.args[0] is ere._CheckinFailed


@pytest.mark.parametrize("minutes,stuck", [(29, False), (30, True)])
def test_scheduled_stale_boundary_is_30_minutes(setup, minutes, stuck):
    d = dep_id()
    setup(FakeClient({f"{MAX}/WAAA": d}, [make_run(StateType.SCHEDULED, deployment_id=d, created=ago(minutes))]))
    assert ere.main(["--codes", "WAAA"]) == (ere.EXIT_ERRORS if stuck else ere.EXIT_OK)


def test_stale_pending_run_is_set_to_cancelling(setup, capsys):
    d = dep_id()
    stuck = make_run(StateType.PENDING, deployment_id=d, created=ago(40), state_since=ago(25))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stuck]))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.state_writes == [(stuck.id, StateType.CANCELLING, "watchdog: stuck in Pending for 25 min", False)]
    assert client.created == []
    out = capsys.readouterr().out
    assert "stale_pending_cancelled=1" in out and "deferred=1" in out


@pytest.mark.parametrize("minutes, stale", [(9, False), (10, True)])
def test_pending_boundary_is_10_minutes(setup, minutes, stale):
    d = dep_id()
    run = make_run(StateType.PENDING, deployment_id=d, created=ago(30), state_since=ago(minutes))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    ere.main(["--codes", "WAAA"])
    assert bool(client.state_writes) is stale
    assert client.created == []


# --- Cancelling runs -----------------------------------------------------------------------------------------


def test_stale_cancelling_closed_and_new_run_created(setup):
    d = dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=d, created=ago(400), state_since=ago(30))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [(stale.id, StateType.CANCELLED, "watchdog: stale cancellation", True)]
    assert client.created == [d]


@pytest.mark.parametrize("minutes, closed", [(9, False), (10, True)])
def test_cancelling_boundary_is_10_minutes(setup, minutes, closed):
    d = dep_id()
    run = make_run(StateType.CANCELLING, deployment_id=d, created=ago(60), state_since=ago(minutes))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    ere.main(["--codes", "WAAA"])
    assert bool(client.state_writes) is closed
    assert client.created == ([d] if closed else [])


def test_recent_cancelling_defers_new_run(setup, capsys):
    d = dep_id()
    fresh = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(2))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [fresh]))
    ere.main(["--codes", "WAAA"])
    assert client.state_writes == [] and client.created == []
    assert "deferred=1" in capsys.readouterr().out


def test_rejected_close_is_not_counted_and_defers(setup, capsys):
    d = dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(60))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale], reject_ids=[stale.id]))
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_ERRORS
    assert client.created == []
    out = capsys.readouterr().out
    assert "closed stale cancellation NOT applied" in out and "was REJECT" in out
    assert "stale_cancels_closed=0" in out and "rejected=1" in out and "deferred=1" in out


def test_rejected_zombie_cancel_is_not_counted(setup, capsys):
    d = dep_id()
    zombie = make_run(StateType.RUNNING, deployment_id=d, created=ago(240), start_time=ago(240))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [zombie], reject_ids=[zombie.id]))
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_ERRORS
    assert client.created == []
    out = capsys.readouterr().out
    assert "zombies_cancelled=0" in out and "rejected=1" in out


# --- Starting runs, dry run, targets -------------------------------------------------------------------------


def test_no_runs_at_all_starts_one(setup):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))
    assert ere.main(["--codes", "WAAA"]) == 0
    assert client.created == [d]


def test_dry_run_writes_nothing(setup, capsys, sentry):
    a, b = dep_id(), dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=a, state_since=ago(60))
    zombie = make_run(StateType.RUNNING, deployment_id=b, created=ago(240), start_time=ago(240))
    other = make_run(StateType.CANCELLING, deployment_id=dep_id(), state_since=ago(60))
    client = setup(
        FakeClient({f"{MAX}/WAAA": a, f"{MAX}/WBBB": b}, [stale, zombie, other]),
        targets=(f"{MAX}/WAAA", f"{MAX}/WBBB"),
    )
    assert ere.main(["--dry-run"]) == 0
    assert client.state_writes == [] and client.created == []
    out = capsys.readouterr().out
    assert f"{MAX}/WAAA: [dry-run] would create a new flow run" in out
    assert "[dry-run] Summary:" in out
    # WAAA's stale cancellation is closed by its station check; the sweep afterwards closes only `other`.
    assert "started=1 zombies_cancelled=1 stale_pending_cancelled=0 stale_cancels_closed=2 deferred=1" in out
    sentry.init.assert_not_called()


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


STATIONS_YAML = """
stations:
  - code: "KAAA - 1.1 FM"
    name: "A"
    url: "https://a.example/stream"
    state: "Texas"
    recorder: max
  - code: "KBBB - 2.2 AM"
    name: "B"
    url: "https://b.example/stream"
    state: "Texas"
    recorder: lite
  - code: "KCCC - 3.3 FM"
    name: "C"
    url: "https://c.example/player"
    state: "Texas"
    recorder: generic
    process_group: radio_kccc
    driver:
      sink: kccc_sink
      source: kccc_sink.monitor
      play_button_selector: "button.play"
      video_element_selector: "video"
  - code: "KDDD - 4.4 FM"
    name: "D (disabled)"
    url: "https://d.example/stream"
    state: "Texas"
    recorder: max
    enabled: false
"""


def test_targets_come_from_the_station_list(tmp_path, monkeypatch):
    path = tmp_path / "stations.yaml"
    path.write_text(STATIONS_YAML, encoding="utf-8")
    monkeypatch.setenv("STATIONS_CONFIG", str(path))
    assert ere.select_targets(None) == [
        "Audio Recording: Max Recorder/KAAA - 1.1 FM",
        "Audio Recording: Lite Recorder/KBBB - 2.2 AM",
        "Generic Audio Recording/KCCC - 3.3 FM",
    ]
    assert ere.select_targets(["KBBB - 2.2 AM", "KDDD - 4.4 FM"]) == ["Audio Recording: Lite Recorder/KBBB - 2.2 AM"]


# --- Global sweep and ordering -------------------------------------------------------------------------------


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


def test_station_checks_run_before_the_sweep_and_a_sweep_failure_is_counted(setup, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))
    original = client.read_flow_runs

    async def read(*, flow_run_filter, **kwargs):
        if flow_run_filter.deployment_id is None:  # the sweep's unfiltered read
            raise http_500()
        return await original(flow_run_filter=flow_run_filter, **kwargs)

    client.read_flow_runs = read
    assert ere.main([]) == ere.EXIT_ERRORS
    assert client.created == [d]
    out = capsys.readouterr().out
    assert "Stale-cancellation sweep failed: PrefectHTTPStatusError" in out
    assert "Traceback" not in out
    assert "started=1" in out and "errors=1" in out


# --- Errors, exit status and Sentry --------------------------------------------------------------------------


def test_per_station_error_is_counted_and_fails_the_exit_status(setup, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def boom(deployment_id):
        raise RuntimeError("409 conflict")

    client.create_flow_run_from_deployment = boom
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_ERRORS
    assert "errors=1" in capsys.readouterr().out


def test_http_5xx_on_one_station_does_not_stop_the_others(setup, capsys):
    a, b = dep_id(), dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": a, f"{MAX}/WBBB": b}, []), targets=(f"{MAX}/WAAA", f"{MAX}/WBBB"))
    original = client.read_deployment_by_name

    async def flaky(name):
        if name.endswith("WAAA"):
            raise http_500()
        return await original(name)

    client.read_deployment_by_name = flaky
    assert ere.main(["--codes", "WAAA", "WBBB"]) == ere.EXIT_ERRORS
    assert client.created == [b]
    out = capsys.readouterr().out
    assert f"{MAX}/WAAA: error: PrefectHTTPStatusError" in out
    assert "errors=1" in out


def test_state_write_exception_is_counted(setup, capsys):
    d = dep_id()
    stale = make_run(StateType.CANCELLING, deployment_id=d, state_since=ago(60))
    client = setup(FakeClient({f"{MAX}/WAAA": d}, [stale]))

    async def fail(run_id, state, force=False):
        raise http_500()

    client.set_flow_run_state = fail
    assert ere.main(["--close-stale-cancelling"]) == ere.EXIT_ERRORS
    out = capsys.readouterr().out
    assert "stale_cancels_closed=0" in out and "errors=1" in out


def test_transport_error_mid_run_is_counted_per_station(setup, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def drop(name):
        raise httpx.ConnectError("connection reset")

    client.read_deployment_by_name = drop
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_ERRORS
    assert "errors=1" in capsys.readouterr().out


def test_unreachable_api_exits_1(setup):
    setup(FakeClient(health_error=httpx.ConnectError("refused")))
    assert ere.main([]) == ere.EXIT_UNREACHABLE


def test_client_that_cannot_open_exits_1(setup):
    class Broken(FakeClient):
        async def __aenter__(self):
            raise httpx.ConnectError("refused")

    setup(Broken())
    assert ere.main([]) == ere.EXIT_UNREACHABLE


def test_errors_send_a_sentry_event_and_check_in_as_error(setup, sentry):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def boom(deployment_id):
        raise RuntimeError("409 conflict")

    client.create_flow_run_from_deployment = boom
    assert ere.main([]) == ere.EXIT_ERRORS
    sentry.init.assert_called_once_with(dsn=os.environ["SENTRY_DSN"])
    [call] = sentry.capture_event.call_args_list
    event = call.args[0]
    assert event["level"] == "error"
    assert event["fingerprint"] == ["recording-watchdog", "errors", "2026-10-09T12"]
    assert "1 errors, 0 rejected" in event["message"]
    assert "errors=1" in event["extra"]["summary"]
    sentry.crons.monitor.assert_called_once_with(
        monitor_slug="recording-watchdog",
        monitor_config={
            "schedule": {"type": "crontab", "value": "7,22,37,52 * * * *"},
            "timezone": "UTC",
            "checkin_margin": 5,
            "max_runtime": 10,
        },
    )
    assert sentry.crons.monitor.return_value.__exit__.call_args.args[0] is ere._CheckinFailed
    sentry.flush.assert_called_once_with(timeout=30)


def test_unreachable_api_sends_a_sentry_event(setup, sentry):
    setup(FakeClient(health_error=httpx.ConnectError("refused")))
    assert ere.main([]) == ere.EXIT_UNREACHABLE
    [call] = sentry.capture_event.call_args_list
    assert call.args[0]["fingerprint"] == ["recording-watchdog", "errors", "2026-10-09T12"]
    assert "Prefect API unreachable" in call.args[0]["message"]
    sentry.flush.assert_called_once_with(timeout=30)


def test_clean_tick_checks_in_ok_and_sends_no_event(setup, sentry):
    d = dep_id()
    setup(FakeClient({f"{MAX}/WAAA": d}, [make_run(StateType.SCHEDULED, deployment_id=d)]))
    assert ere.main([]) == 0
    sentry.capture_event.assert_not_called()
    checkin = sentry.crons.monitor.return_value
    checkin.__enter__.assert_called_once()
    assert checkin.__exit__.call_args.args[0] is None


def test_manual_codes_run_reports_errors_without_a_check_in(setup, sentry):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))

    async def boom(deployment_id):
        raise RuntimeError("409 conflict")

    client.create_flow_run_from_deployment = boom
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_ERRORS
    sentry.crons.monitor.assert_not_called()
    sentry.capture_event.assert_called_once()


def test_no_sentry_without_dsn(setup, sentry, monkeypatch):
    monkeypatch.delenv("SENTRY_DSN")
    setup(FakeClient(health_error=httpx.ConnectError("refused")))
    assert ere.main([]) == ere.EXIT_UNREACHABLE
    sentry.init.assert_not_called()
    sentry.capture_event.assert_not_called()


# --- Lock ----------------------------------------------------------------------------------------------------


def test_lock_held_skips_the_tick_with_exit_0(setup, lock_file, capsys, sentry):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))
    held = ere.acquire_lock(str(lock_file))
    try:
        assert ere.main([]) == 0
    finally:
        os.close(held)
    assert client.created == [] and client.read_calls == []
    assert "watchdog: restart in progress, skipping tick" in capsys.readouterr().out
    # The skipped tick still checks in OK, so a restart does not page as a missed watchdog run.
    assert sentry.crons.monitor.return_value.__exit__.call_args.args[0] is None


def test_lock_is_released_after_a_tick(setup, lock_file):
    setup(FakeClient({}, []), targets=())
    ere.main([])
    fd = ere.acquire_lock(str(lock_file))
    assert fd is not None
    os.close(fd)


def test_lock_path_defaults_to_the_shared_file(monkeypatch):
    monkeypatch.delenv("RECORDING_LOCK_FILE")
    assert ere.lock_file_path() == "/tmp/verdad-recording.lock"


def test_naive_timestamps_are_treated_as_utc():
    assert ere._age_minutes(datetime(2026, 10, 9, 11, 30), NOW) == 30
    assert ere._age_minutes(None, NOW) is None


# --- Worker machines (VER-429) -------------------------------------------------------------------------------


class FakeFly:
    """Stands in for flyctl: `machine list -a APP --json` answers from `apps`, `machine start` is recorded."""

    def __init__(self, apps, fail_list=(), fail_start=()):
        self.apps = apps
        self.fail_list = set(fail_list)
        self.fail_start = set(fail_start)
        self.calls = []
        self.started = []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("machine", "list"):
            app = args[3]
            if app in self.fail_list:
                raise RuntimeError(f"fly machine list -a {app} exited 1: timeout")
            return ere.json.dumps(self.apps.get(app, []))
        if args[:2] == ("machine", "start"):
            if args[2] in self.fail_start:
                raise RuntimeError("fly machine start exited 1: host unavailable")
            self.started.append((args[4], args[2]))
            return ""
        raise AssertionError(f"unexpected flyctl call: {args}")


def machine(machine_id, state, minutes_ago=60, name="m", events=True):
    """A `fly machine list --json` entry whose newest event (the stop) is `minutes_ago` old."""
    m = {"id": machine_id, "name": name, "state": state, "updated_at": ago(600).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if events:
        m["events"] = [
            {"type": "exit", "status": "stopped", "timestamp": int(ago(minutes_ago).timestamp() * 1000)},
            {"type": "start", "status": "started", "timestamp": int(ago(minutes_ago + 30).timestamp() * 1000)},
        ]
    else:
        m["updated_at"] = ago(minutes_ago).strftime("%Y-%m-%dT%H:%M:%SZ")
    return m


@pytest.fixture
def fly(monkeypatch):
    def _fly(apps, ids, **kw):
        fake = FakeFly(apps, **kw)
        monkeypatch.setenv("FLY_MACHINE_IDS", ids)
        monkeypatch.setattr(ere, "_fly", fake)
        monkeypatch.setattr(ere.shutil, "which", lambda name: "/usr/local/bin/fly")
        return fake

    return _fly


def healthy_client(setup):
    d = dep_id()
    return setup(FakeClient({f"{MAX}/WAAA": d}, [make_run(StateType.SCHEDULED, deployment_id=d)]))


def test_stopped_worker_machine_is_started(setup, fly, sentry, capsys):
    healthy_client(setup)
    fake = fly(
        {"recording-worker": [machine("max1", "stopped", 180, "max"), machine("lite1", "started")]},
        "max1, lite1",
    )
    assert ere.main([]) == ere.EXIT_OK
    assert fake.started == [("recording-worker", "max1")]
    out = capsys.readouterr().out
    assert "started recording-worker/max1 (max), which was stopped for 180 min" in out
    assert "machines_started=1" in out
    [call] = sentry.capture_event.call_args_list
    assert call.args[0]["level"] == "warning"
    assert call.args[0]["fingerprint"] == ["recording-watchdog", "machines", "2026-10-09T12"]
    assert sentry.crons.monitor.return_value.__exit__.call_args.args[0] is None


@pytest.mark.parametrize("minutes,starts", [(4, False), (5, True)])
def test_stop_time_falls_back_to_updated_at_without_events(setup, fly, minutes, starts):
    healthy_client(setup)
    fake = fly({"recording-worker": [machine("max1", "stopped", minutes, events=False)]}, "max1")
    assert ere.main([]) == ere.EXIT_OK
    assert fake.started == ([("recording-worker", "max1")] if starts else [])


def test_suspended_machine_is_started_too(setup, fly):
    healthy_client(setup)
    fake = fly({"processing-worker": [machine("emb1", "suspended")]}, "emb1")
    assert ere.main([]) == ere.EXIT_OK
    assert fake.started == [("processing-worker", "emb1")]


@pytest.mark.parametrize("minutes,starts", [(4, False), (5, True)])
def test_recently_stopped_machine_waits_for_a_later_tick(setup, fly, minutes, starts):
    healthy_client(setup)
    fake = fly({"recording-worker": [machine("max1", "stopped", minutes)]}, "max1")
    assert ere.main([]) == ere.EXIT_OK
    assert fake.started == ([("recording-worker", "max1")] if starts else [])


def test_machines_outside_the_list_and_running_machines_are_left_alone(setup, fly, sentry):
    healthy_client(setup)
    fake = fly(
        {
            "recording-worker": [machine("max1", "started"), machine("lite1", "replacing")],
            "processing-worker": [machine("undo1", "stopped")],
        },
        "max1,lite1",
    )
    assert ere.main([]) == ere.EXIT_OK
    assert fake.started == []
    sentry.capture_event.assert_not_called()


def test_listing_failure_is_counted_and_the_prefect_checks_still_run(setup, fly, capsys):
    d = dep_id()
    client = setup(FakeClient({f"{MAX}/WAAA": d}, []))
    fake = fly(
        {"generic-recording-worker": [machine("waqi1", "stopped")]}, "waqi1", fail_list=["recording-worker"]
    )
    assert ere.main([]) == ere.EXIT_ERRORS
    assert fake.started == [("generic-recording-worker", "waqi1")]
    assert client.created == [d]
    out = capsys.readouterr().out
    assert "listing recording-worker failed" in out and "errors=1" in out


def test_start_failure_is_counted(setup, fly, capsys):
    healthy_client(setup)
    fly({"recording-worker": [machine("max1", "stopped")]}, "max1", fail_start=["max1"])
    assert ere.main([]) == ere.EXIT_ERRORS
    assert "starting recording-worker/max1 (m) failed" in capsys.readouterr().out


def test_machine_check_runs_even_when_the_prefect_api_is_down(setup, fly):
    setup(FakeClient(health_error=httpx.ConnectError("refused")))
    fake = fly({"recording-worker": [machine("max1", "stopped")]}, "max1")
    assert ere.main([]) == ere.EXIT_UNREACHABLE
    assert fake.started == [("recording-worker", "max1")]


def test_dry_run_starts_no_machine(setup, fly, capsys):
    healthy_client(setup)
    fake = fly({"recording-worker": [machine("max1", "stopped")]}, "max1")
    assert ere.main(["--dry-run"]) == ere.EXIT_OK
    assert fake.started == []
    assert "[dry-run] would start recording-worker/max1" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["--codes", "WAAA"], ["--close-stale-cancelling"]])
def test_manual_runs_do_not_touch_machines(setup, fly, argv):
    healthy_client(setup)
    fake = fly({"recording-worker": [machine("max1", "stopped")]}, "max1")
    ere.main(argv)
    assert fake.calls == []


def test_machine_check_is_skipped_while_a_restart_holds_the_lock(setup, fly, lock_file):
    healthy_client(setup)
    fake = fly({"recording-worker": [machine("max1", "stopped")]}, "max1")
    fd = ere.acquire_lock(str(lock_file))
    try:
        assert ere.main([]) == ere.EXIT_OK
    finally:
        os.close(fd)
    assert fake.calls == []


def test_unknown_machine_id_is_warned_about(setup, fly, capsys):
    healthy_client(setup)
    fly({"recording-worker": [machine("max1", "started")]}, "max1,gone1")
    assert ere.main([]) == ere.EXIT_OK
    assert "WARNING gone1 from FLY_MACHINE_IDS is not in" in capsys.readouterr().out


def test_missing_flyctl_is_an_error_when_machine_ids_are_set(setup, monkeypatch, capsys):
    healthy_client(setup)
    monkeypatch.setenv("FLY_MACHINE_IDS", "max1")
    monkeypatch.setattr(ere.shutil, "which", lambda name: None)
    assert ere.main([]) == ere.EXIT_ERRORS
    assert "fly is not on PATH" in capsys.readouterr().out


def test_fly_helper_raises_on_non_zero_exit(monkeypatch):
    monkeypatch.undo()  # the real _fly, with subprocess faked
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: machine not found")

    monkeypatch.setattr(ere.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="machine not found"):
        ere._fly("machine", "start", "x", "-a", "recording-worker")
    assert calls[0][0] == ["fly", "machine", "start", "x", "-a", "recording-worker"]
    assert calls[0][1]["timeout"] == ere.FLY_TIMEOUT_SECONDS


def test_stuck_runs_are_not_a_failure_on_the_tick_that_starts_their_machine(setup, fly, sentry, capsys):
    d = dep_id()
    late = make_run(StateType.SCHEDULED, deployment_id=d, created=ago(120))
    setup(FakeClient({f"{MAX}/WAAA": d}, [late]))
    fly({"recording-worker": [machine("max1", "stopped", 120)]}, "max1")
    assert ere.main([]) == ere.EXIT_OK
    assert "stuck_scheduled=1 machines_started=1" in capsys.readouterr().out
    [call] = sentry.capture_event.call_args_list
    assert call.args[0]["level"] == "warning"


def test_scheduled_run_due_later_is_not_stuck(setup):
    d = dep_id()
    run = make_run(StateType.SCHEDULED, deployment_id=d, created=ago(120))
    run.expected_start_time = ago(10)
    setup(FakeClient({f"{MAX}/WAAA": d}, [run]))
    assert ere.main(["--codes", "WAAA"]) == ere.EXIT_OK


def test_non_list_listing_is_an_error_for_that_app_only(setup, fly, monkeypatch, capsys):
    healthy_client(setup)
    fake = fly({"generic-recording-worker": [machine("waqi1", "stopped")]}, "waqi1")
    real = fake.__call__

    def odd(*args):
        if args[:4] == ("machine", "list", "-a", "recording-worker"):
            return '{"error": "unauthorized"}'
        return real(*args)

    monkeypatch.setattr(ere, "_fly", odd)
    assert ere.main([]) == ere.EXIT_ERRORS
    assert fake.started == [("generic-recording-worker", "waqi1")]
    assert "expected a JSON list, got dict" in capsys.readouterr().out


def test_flyctl_timeout_is_an_error_for_that_app_only(setup, fly, monkeypatch, capsys):
    healthy_client(setup)
    fake = fly({"processing-worker": [machine("emb1", "stopped")]}, "emb1")
    real = fake.__call__

    def slow(*args):
        if args[:4] == ("machine", "list", "-a", "recording-worker"):
            raise ere.subprocess.TimeoutExpired(cmd="fly", timeout=ere.FLY_TIMEOUT_SECONDS)
        return real(*args)

    monkeypatch.setattr(ere, "_fly", slow)
    assert ere.main([]) == ere.EXIT_ERRORS
    assert fake.started == [("processing-worker", "emb1")]
    assert "TimeoutExpired" in capsys.readouterr().out


def test_spent_budget_skips_the_rest_and_counts_one_error(setup, fly, monkeypatch, capsys):
    healthy_client(setup)
    fake = fly(
        {"recording-worker": [machine("max1", "stopped")], "processing-worker": [machine("emb1", "stopped")]},
        "max1,emb1,gone1",
    )
    clock = iter([0, 0, 0, 500, 500, 500, 500, 500])
    monkeypatch.setattr(ere.time, "monotonic", lambda: next(clock, 500))
    assert ere.main([]) == ere.EXIT_ERRORS
    out = capsys.readouterr().out
    assert out.count("budget spent") == 1 and "errors=1" in out
    assert len(fake.started) <= 1
    assert "gone1" not in out
