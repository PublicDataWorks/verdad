#!/usr/bin/env python3
"""Cancel every Running/Pending/Scheduled flow run before restart_all.sh restarts the worker machines.

Setting a run to Cancelling only asks its runner to stop; the runner polls about every 10 s and then
moves the run to Cancelled. restart_all.sh used to restart the machines 2 s later, so live runs got
SIGTERM mid-cancellation, Prefect marked them Crashed ("Crash detected! Execution was aborted...")
and Sentry reported every one (VER-424). This script now waits, up to CANCEL_WAIT_SECONDS, for the
runs it touched to leave Cancelling/Running. Whatever is still Cancelling after that belongs to a dead
worker that will never finish the cancellation, so it is forced to Cancelled.

Scheduled runs (including Late ones the recording watchdog leaves alone while no worker picks them up) are
cancelled too; otherwise one would survive the restart and start_recording.sh would add a second run next to
it. A Scheduled run has no infrastructure, so the server's BypassCancellingFlowRunsWithNoInfra rule REJECTs
Scheduled -> Cancelling and sets Cancelled directly; that result counts as cancelled and is not waited on.

Every write checks the OrchestrationResult it gets back: ACCEPT is done, anything else (REJECT, ABORT, WAIT)
is reported as not applied.

Exit status: 1 when the Prefect API cannot be reached, 0 otherwise.
"""

import asyncio
import os
import time

from prefect import get_client
from prefect.client.schemas.filters import (
    FlowRunFilter,
    FlowRunFilterId,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import StateType
from prefect.client.schemas.responses import SetStateStatus
from prefect.client.schemas.sorting import FlowRunSort
from prefect.states import Cancelled, Cancelling

CANCEL_WAIT_SECONDS = float(os.getenv("CANCEL_WAIT_SECONDS", "90"))
POLL_INTERVAL_SECONDS = float(os.getenv("CANCEL_POLL_INTERVAL_SECONDS", "5"))
# The Prefect server rejects /flow_runs/filter with limit > 200.
PAGE_SIZE = 200
CANCEL_STATES = [StateType.RUNNING, StateType.PENDING, StateType.SCHEDULED]


def _status(result):
    status = getattr(result, "status", None)
    return getattr(status, "value", status)


def _reason(result) -> str:
    return getattr(getattr(result, "details", None), "reason", None) or "no reason"


def _result_type(result):
    state = getattr(result, "state", None)
    return getattr(state, "type", None)


async def read_all_flow_runs(client, flow_run_filter: FlowRunFilter) -> list:
    runs: list = []
    offset = 0
    while True:
        page = await client.read_flow_runs(
            flow_run_filter=flow_run_filter, sort=FlowRunSort.ID_DESC, limit=PAGE_SIZE, offset=offset
        )
        runs.extend(page)
        if len(page) < PAGE_SIZE:
            return runs
        offset += PAGE_SIZE


async def still_cancelling(client, run_ids: list) -> dict:
    """Runs among run_ids that are still Cancelling or Running, as {id: run}."""
    pending = {}
    for i in range(0, len(run_ids), PAGE_SIZE):
        chunk = run_ids[i : i + PAGE_SIZE]
        runs = await read_all_flow_runs(
            client,
            FlowRunFilter(
                id=FlowRunFilterId(any_=chunk),
                state=FlowRunFilterState(type=FlowRunFilterStateType(any_=[StateType.CANCELLING, StateType.RUNNING])),
            ),
        )
        pending.update({r.id: r for r in runs})
    return pending


async def wait_for_cancellation(client, run_ids: list, timeout: float = None, interval: float = None) -> dict:
    """Poll until every run in run_ids has left Cancelling/Running or the timeout passes.

    Returns the runs that are still Cancelling/Running when it gives up (empty when all finished).
    """
    timeout = CANCEL_WAIT_SECONDS if timeout is None else timeout
    interval = POLL_INTERVAL_SECONDS if interval is None else interval
    deadline = time.monotonic() + timeout
    pending = await still_cancelling(client, run_ids)
    while pending and time.monotonic() < deadline:
        await asyncio.sleep(interval)
        pending = await still_cancelling(client, list(pending))
    return pending


async def cancel_all_runs():
    try:
        async with get_client() as client:
            runs = await read_all_flow_runs(
                client,
                FlowRunFilter(state=FlowRunFilterState(type=FlowRunFilterStateType(any_=CANCEL_STATES))),
            )

            cancelled_count = 0
            direct_count = 0
            rejected_count = 0
            failed_count = 0
            touched = []

            for run in runs:
                try:
                    result = await client.set_flow_run_state(
                        run.id,
                        state=Cancelling(message="Cancelled by scheduled restart"),
                    )
                except Exception as e:
                    print(f"- Failed to cancel {run.name} ({run.id}): {e}")
                    failed_count += 1
                    continue
                if result.status == SetStateStatus.ACCEPT:
                    print(f"- Cancelling: {run.name} ({run.id})")
                    cancelled_count += 1
                    touched.append(run.id)
                elif result.status == SetStateStatus.REJECT and _result_type(result) == StateType.CANCELLED:
                    # Scheduled run with no infrastructure: the server went straight to Cancelled.
                    print(f"- Cancelled (no infrastructure): {run.name} ({run.id})")
                    direct_count += 1
                else:
                    print(f"- Cancel NOT applied to {run.name} ({run.id}): {_status(result)}: {_reason(result)}")
                    rejected_count += 1

            print(
                f"\nSummary: {cancelled_count} flow runs set to Cancelling, {direct_count} cancelled directly, "
                f"{rejected_count} rejected"
            )
            if failed_count > 0:
                print(f"Failed to cancel {failed_count} flow runs")
            if len(runs) == 0:
                print("No running, pending or scheduled flow runs found")
                return

            if not touched:
                return

            print(f"Waiting up to {CANCEL_WAIT_SECONDS:g}s for {len(touched)} runs to finish cancelling...")
            leftover = await wait_for_cancellation(client, touched)
            finished = len(touched) - len(leftover)

            forced = 0
            force_failed = 0
            still_running = 0
            for run in leftover.values():
                if run.state_type != StateType.CANCELLING:
                    # Still Running: its runner has not seen the Cancelling state yet, or a later
                    # transition put it back. Leave it; the machine restart ends it.
                    still_running += 1
                    continue
                try:
                    result = await client.set_flow_run_state(
                        run.id,
                        state=Cancelled(message="Forced by scheduled restart: worker did not finish cancelling"),
                        force=True,
                    )
                except Exception as e:
                    print(f"- Failed to force {run.name} ({run.id}) to Cancelled: {e}")
                    force_failed += 1
                    continue
                if result.status == SetStateStatus.ACCEPT:
                    forced += 1
                else:
                    print(
                        f"- Force to Cancelled NOT applied to {run.name} ({run.id}): {_status(result)}: {_reason(result)}"
                    )
                    force_failed += 1

            print(
                f"Cancellation wait: {finished} finished, {forced} forced to Cancelled, "
                f"{still_running} still running, {force_failed} failed to force"
            )

    except Exception as e:
        print(f"Error connecting to Prefect API: {e}")
        exit(1)


if __name__ == "__main__":
    asyncio.run(cancel_all_runs())
