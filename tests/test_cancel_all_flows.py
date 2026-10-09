"""Tests for src/scripts/cancel_all_flows.py: cancel, wait for the runners, force dead-worker runs (VER-424).
No network: the Prefect client is a fake, and asyncio.sleep / time.monotonic are patched."""

import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from prefect.client.schemas.objects import StateType
from prefect.client.schemas.responses import (
    OrchestrationResult,
    SetStateStatus,
    StateAcceptDetails,
    StateRejectDetails,
)
from prefect.states import Cancelled, State

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src", "scripts"))

import cancel_all_flows as caf  # noqa: E402


def make_run(state_type):
    return SimpleNamespace(id=uuid.uuid4(), name=f"run-{uuid.uuid4().hex[:6]}", state_type=state_type)


def accepted(state):
    return OrchestrationResult(state=state, status=SetStateStatus.ACCEPT, details=StateAcceptDetails())


def rejected(state, reason):
    return OrchestrationResult(state=state, status=SetStateStatus.REJECT, details=StateRejectDetails(reason=reason))


class FakeClient:
    """Runs whose id is in `live` finish cancelling after `finish_after_polls` reads of their state;
    every other run touched stays Cancelling (its worker is dead).

    set_flow_run_state answers like the server: ACCEPT normally; Scheduled -> Cancelling is REJECTed with a
    Cancelled state (BypassCancellingFlowRunsWithNoInfra); ids in reject_cancel / reject_force get a plain
    REJECT that leaves the run where it was; ids in raise_cancel raise (an HTTP error)."""

    def __init__(self, runs, live=(), finish_after_polls=1, reject_cancel=(), reject_force=(), raise_cancel=()):
        self.runs = runs
        self.live = set(live)
        self.finish_after_polls = finish_after_polls
        self.reject_cancel = set(reject_cancel)
        self.reject_force = set(reject_force)
        self.raise_cancel = set(raise_cancel)
        self.polls = 0
        self.writes = []
        self.read_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read_flow_runs(self, *, flow_run_filter, sort=None, limit=None, offset=0):
        assert limit is not None and limit <= 200
        self.read_calls.append(offset)
        states = set(flow_run_filter.state.type.any_)
        ids = set(flow_run_filter.id.any_) if flow_run_filter.id else None
        if ids is not None and offset == 0:
            self.polls += 1
            if self.polls > self.finish_after_polls:
                for r in self.runs:
                    if r.id in self.live and r.state_type == StateType.CANCELLING:
                        r.state_type = StateType.CANCELLED
        matching = [r for r in self.runs if r.state_type in states and (ids is None or r.id in ids)]
        return matching[offset : offset + limit]

    async def set_flow_run_state(self, run_id, state, force=False):
        run = next(r for r in self.runs if r.id == run_id)
        if state.type == StateType.CANCELLING and run_id in self.raise_cancel:
            raise RuntimeError("500 Internal Server Error")
        if (state.type == StateType.CANCELLING and run_id in self.reject_cancel) or (
            state.type == StateType.CANCELLED and run_id in self.reject_force
        ):
            return rejected(State(type=run.state_type), "This run cannot transition to the proposed state.")
        self.writes.append((run_id, state.type, force))
        if state.type == StateType.CANCELLING and run.state_type == StateType.SCHEDULED:
            run.state_type = StateType.CANCELLED
            return rejected(Cancelled(), "Scheduled flow run has no infrastructure to terminate.")
        run.state_type = state.type
        return accepted(state)


@pytest.fixture
def no_wait(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    clock = [0.0]
    monkeypatch.setattr(caf.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(caf.time, "monotonic", lambda: clock[0])
    return sleeps


def run_with(monkeypatch, client):
    monkeypatch.setattr(caf, "get_client", lambda: client)
    import asyncio

    asyncio.run(caf.cancel_all_runs())


def test_live_runs_finish_and_nothing_is_forced(monkeypatch, no_wait, capsys):
    runs = [make_run(StateType.RUNNING) for _ in range(3)]
    client = FakeClient(runs, live=[r.id for r in runs], finish_after_polls=2)
    run_with(monkeypatch, client)
    assert [w[1] for w in client.writes] == [StateType.CANCELLING] * 3
    assert len(no_wait) == 2  # waited two poll intervals, then all were Cancelled
    assert "3 finished, 0 forced to Cancelled" in capsys.readouterr().out


def test_dead_worker_runs_are_forced_after_the_timeout(monkeypatch, no_wait, capsys):
    live = make_run(StateType.RUNNING)
    dead = [make_run(StateType.RUNNING), make_run(StateType.PENDING)]
    client = FakeClient([live, *dead], live=[live.id])
    run_with(monkeypatch, client)
    forced = [w for w in client.writes if w[1] == StateType.CANCELLED]
    assert {w[0] for w in forced} == {r.id for r in dead}
    assert all(w[2] is True for w in forced)
    assert sum(no_wait) >= caf.CANCEL_WAIT_SECONDS
    assert "1 finished, 2 forced to Cancelled" in capsys.readouterr().out


def test_pagination_over_200_runs(monkeypatch, no_wait):
    runs = [make_run(StateType.RUNNING) for _ in range(450)]
    client = FakeClient(runs, live=[r.id for r in runs], finish_after_polls=0)
    run_with(monkeypatch, client)
    assert client.read_calls[:3] == [0, 200, 400]
    assert sum(1 for w in client.writes if w[1] == StateType.CANCELLING) == 450
    assert not any(w[1] == StateType.CANCELLED for w in client.writes)


def test_no_runs_skips_the_wait(monkeypatch, no_wait, capsys):
    client = FakeClient([])
    run_with(monkeypatch, client)
    assert no_wait == []
    assert "No running, pending or scheduled flow runs found" in capsys.readouterr().out


def test_rejected_cancel_and_rejected_force_are_not_counted_as_done(monkeypatch, no_wait, capsys):
    a, b, c = (make_run(StateType.RUNNING) for _ in range(3))
    client = FakeClient([a, b, c], reject_cancel=[a.id], reject_force=[b.id])
    run_with(monkeypatch, client)
    out = capsys.readouterr().out
    assert f"Cancel NOT applied to {a.name} ({a.id}): REJECT" in out
    assert "2 flow runs set to Cancelling, 0 cancelled directly, 1 rejected" in out
    assert f"Force to Cancelled NOT applied to {b.name} ({b.id}): REJECT" in out
    assert "0 finished, 1 forced to Cancelled, 0 still running, 1 failed to force" in out
    # The rejected run was never Cancelling, so it is neither waited on nor forced.
    assert a.state_type == StateType.RUNNING
    assert not any(w[0] == a.id for w in client.writes)


def test_cancel_exception_is_reported(monkeypatch, no_wait, capsys):
    a, b = make_run(StateType.RUNNING), make_run(StateType.RUNNING)
    client = FakeClient([a, b], live=[b.id], raise_cancel=[a.id])
    run_with(monkeypatch, client)
    out = capsys.readouterr().out
    assert "Failed to cancel 1 flow runs" in out
    assert "1 finished, 0 forced" in out


def test_all_cancels_rejected_skips_the_wait(monkeypatch, no_wait):
    a = make_run(StateType.RUNNING)
    client = FakeClient([a], reject_cancel=[a.id])
    run_with(monkeypatch, client)
    assert no_wait == []


def test_scheduled_runs_are_cancelled_directly_and_not_waited_on(monkeypatch, no_wait, capsys):
    # A Late run the watchdog left alone during an outage must not survive the restart.
    late = make_run(StateType.SCHEDULED)
    live = make_run(StateType.RUNNING)
    client = FakeClient([late, live], live=[live.id], finish_after_polls=0)
    run_with(monkeypatch, client)
    assert late.state_type == StateType.CANCELLED
    out = capsys.readouterr().out
    assert f"Cancelled (no infrastructure): {late.name}" in out
    assert "1 flow runs set to Cancelling, 1 cancelled directly, 0 rejected" in out
    assert "1 finished, 0 forced to Cancelled" in out
    assert not any(w[1] == StateType.CANCELLED for w in client.writes)


def test_only_scheduled_runs_skip_the_wait(monkeypatch, no_wait):
    client = FakeClient([make_run(StateType.SCHEDULED) for _ in range(3)])
    run_with(monkeypatch, client)
    assert no_wait == []
    assert all(r.state_type == StateType.CANCELLED for r in client.runs)


def test_cancel_filter_includes_scheduled():
    assert set(caf.CANCEL_STATES) == {StateType.RUNNING, StateType.PENDING, StateType.SCHEDULED}


def test_runs_still_running_are_left_alone(monkeypatch, no_wait, capsys):
    a = make_run(StateType.RUNNING)
    client = FakeClient([a])

    async def leftover(client_, run_ids, timeout=None, interval=None):
        return {a.id: SimpleNamespace(id=a.id, name=a.name, state_type=StateType.RUNNING)}

    monkeypatch.setattr(caf, "wait_for_cancellation", leftover)
    run_with(monkeypatch, client)
    assert not any(w[1] == StateType.CANCELLED for w in client.writes)
    assert "1 still running" in capsys.readouterr().out


def test_api_failure_exits_1(monkeypatch):
    class Broken(FakeClient):
        async def read_flow_runs(self, **kwargs):
            raise ConnectionError("refused")

    monkeypatch.setattr(caf, "get_client", lambda: Broken([]))
    import asyncio

    with pytest.raises(SystemExit) as exc:
        asyncio.run(caf.cancel_all_runs())
    assert exc.value.code == 1
