#!/usr/bin/env python3
"""Recording watchdog (VER-421): make sure every enabled station has a live Prefect flow run.

Flow runs for the recorders are created only by ``scripts/start_recording.sh``, which
``scripts/restart_all.sh`` calls every 6 hours. When a recorder worker dies between restarts its
flow runs are not marked Crashed: max/lite runs stay in **Running** forever (zombies), so "the
deployment has an active run" says nothing about liveness. The heartbeat that does work is task
activity: a healthy recording run starts a ``capture_audio_stream`` task (then an upload and a
database insert) at least every 30 minutes, one per 1800 s chunk.

For each ``"<flow name>/<code>"`` from ``stations.prefect_run_targets()`` (the same list
start_recording.sh uses) this script:

- leaves the deployment alone if it has a Scheduled (including Late) or Pending run; one older than
  ``SCHEDULED_STALE_MINUTES`` is logged as a warning, because it means no worker is picking it up and
  another run would only queue behind it;
- treats a Running run as healthy if it started, or its newest task run started, within
  ``RUNNING_IDLE_MINUTES``; any other Running run is a zombie and is forced to Crashed;
- forces Cancelling runs older than ``CANCELLING_STALE_MINUTES`` to Cancelled (their worker is gone, so
  cancellation never completes);
- creates one new flow run when no healthy run remains (a recent Cancelling run defers that to the next
  tick, since it is still on its way out).

A normal run (no ``--codes``) first sweeps every deployment, processing ones included, for stale
Cancelling runs, so ``delete_flow_runs.py`` can delete them. ``--close-stale-cancelling`` does only
that sweep. Cron runs this at :07/:22/:37/:52 under ``flock -n /tmp/verdad-recording.lock`` so it
never overlaps restart_all.sh, which holds the same lock.

Exit status is non-zero only when the Prefect API cannot be reached.
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Make `stations` importable both from a checkout (src/scripts/ -> src/) and inside the prefect
# image, where Dockerfile.prefect puts this file in /app and stations.py in /app/src.
_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE.parent, _HERE / "src"):
    if (_candidate / "stations.py").is_file() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import httpx  # noqa: E402
from prefect import get_client  # noqa: E402
from prefect.client.schemas.filters import (  # noqa: E402
    FlowRunFilter,
    FlowRunFilterDeploymentId,
    FlowRunFilterId,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import StateType  # noqa: E402
from prefect.client.schemas.sorting import FlowRunSort, TaskRunSort  # noqa: E402
from prefect.exceptions import ObjectNotFound  # noqa: E402
from prefect.states import Cancelled, Crashed  # noqa: E402

import stations  # noqa: E402


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


SCHEDULED_STALE_MINUTES = _env_float("WATCHDOG_SCHEDULED_STALE_MINUTES", 30)
RUNNING_IDLE_MINUTES = _env_float("WATCHDOG_RUNNING_IDLE_MINUTES", 45)
CANCELLING_STALE_MINUTES = _env_float("WATCHDOG_CANCELLING_STALE_MINUTES", 10)
CONCURRENCY = max(1, int(_env_float("WATCHDOG_CONCURRENCY", 8)))
# The Prefect server rejects /flow_runs/filter with limit > 200.
PAGE_SIZE = 200

ACTIVE_STATES = [StateType.SCHEDULED, StateType.PENDING, StateType.RUNNING, StateType.CANCELLING]


class ApiUnreachable(Exception):
    """The Prefect API could not be reached; the only failure that makes the script exit non-zero."""


@dataclass
class Summary:
    checked: int = 0
    healthy: int = 0
    started: int = 0
    zombies_crashed: int = 0
    stale_cancels_closed: int = 0
    deferred: int = 0
    missing: int = 0
    errors: int = 0
    # Runs the global sweep already closed, so a dry run does not count them twice.
    closed_ids: set = field(default_factory=set)

    def line(self) -> str:
        return (
            f"checked={self.checked} healthy={self.healthy} started={self.started} "
            f"zombies_crashed={self.zombies_crashed} stale_cancels_closed={self.stale_cancels_closed} "
            f"deferred={self.deferred} missing={self.missing} errors={self.errors}"
        )


def log(message: str) -> None:
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {message}", flush=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_minutes(ts, now: datetime):
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).total_seconds() / 60


def _state_since(run):
    """When the run entered its current state (falls back to creation time)."""
    state = getattr(run, "state", None)
    return getattr(state, "timestamp", None) or run.created


async def read_all_flow_runs(client, flow_run_filter: FlowRunFilter, sort=FlowRunSort.ID_DESC) -> list:
    """Read every flow run matching the filter, PAGE_SIZE at a time."""
    runs: list = []
    offset = 0
    while True:
        page = await client.read_flow_runs(flow_run_filter=flow_run_filter, sort=sort, limit=PAGE_SIZE, offset=offset)
        runs.extend(page)
        if len(page) < PAGE_SIZE:
            return runs
        offset += PAGE_SIZE


async def newest_task_start(client, flow_run_id):
    tasks = await client.read_task_runs(
        flow_run_filter=FlowRunFilter(id=FlowRunFilterId(any_=[flow_run_id])),
        sort=TaskRunSort.EXPECTED_START_TIME_DESC,
        limit=1,
    )
    if not tasks:
        return None
    return tasks[0].start_time or tasks[0].expected_start_time


async def _force_state(client, run, state, dry_run: bool, label: str) -> bool:
    if dry_run:
        log(f"  [dry-run] would set {run.name} ({run.id}) to {state.name}: {state.message}")
        return True
    try:
        await client.set_flow_run_state(run.id, state=state, force=True)
        log(f"  {label}: {run.name} ({run.id}) -> {state.name}")
        return True
    except httpx.TransportError:
        raise
    except Exception as e:  # noqa: BLE001 - log and keep going; one bad run must not stop the sweep
        log(f"  failed to set {run.name} ({run.id}) to {state.name}: {e}")
        return False


async def check_station(client, target: str, summary: Summary, dry_run: bool, now: datetime) -> None:
    summary.checked += 1
    try:
        deployment = await client.read_deployment_by_name(target)
    except ObjectNotFound:
        log(f"{target}: deployment not found, skipping")
        summary.missing += 1
        return

    runs = await read_all_flow_runs(
        client,
        FlowRunFilter(
            deployment_id=FlowRunFilterDeploymentId(any_=[deployment.id]),
            state=FlowRunFilterState(type=FlowRunFilterStateType(any_=ACTIVE_STATES)),
        ),
    )

    queued = [r for r in runs if r.state_type in (StateType.SCHEDULED, StateType.PENDING)]
    running = [r for r in runs if r.state_type == StateType.RUNNING]
    cancelling = [r for r in runs if r.state_type == StateType.CANCELLING]

    healthy = False
    for run in queued:
        age = _age_minutes(run.created, now)
        if age is not None and age >= SCHEDULED_STALE_MINUTES:
            state_name = run.state.name if run.state else run.state_type.value
            log(
                f"{target}: WARNING {state_name} run {run.name} ({run.id}) is {age:.0f} min old; no worker is picking it up"
            )
        healthy = True

    for run in running:
        started_age = _age_minutes(run.start_time or _state_since(run), now)
        if started_age is not None and started_age < RUNNING_IDLE_MINUTES:
            healthy = True
            continue
        task_age = _age_minutes(await newest_task_start(client, run.id), now)
        if task_age is not None and task_age < RUNNING_IDLE_MINUTES:
            healthy = True
            continue
        idle = task_age if task_age is not None else started_age
        idle_minutes = int(idle) if idle is not None else 0
        log(f"{target}: zombie run {run.name} ({run.id}), no task activity for {idle_minutes} min")
        if await _force_state(
            client,
            run,
            Crashed(message=f"watchdog: no task activity for {idle_minutes} min"),
            dry_run,
            "crashed zombie",
        ):
            summary.zombies_crashed += 1

    in_transition = False
    for run in cancelling:
        if run.id in summary.closed_ids:
            continue
        age = _age_minutes(_state_since(run), now)
        if age is not None and age >= CANCELLING_STALE_MINUTES:
            if await _force_state(
                client, run, Cancelled(message="watchdog: stale cancellation"), dry_run, "closed stale cancellation"
            ):
                summary.stale_cancels_closed += 1
        else:
            in_transition = True

    if healthy:
        summary.healthy += 1
        return
    if in_transition:
        log(f"{target}: a run is still cancelling; deferring a new run to the next tick")
        summary.deferred += 1
        return

    if dry_run:
        log(f"{target}: [dry-run] would create a new flow run")
        summary.started += 1
        return
    new_run = await client.create_flow_run_from_deployment(deployment.id)
    log(f"{target}: no healthy run, created {new_run.name} ({new_run.id})")
    summary.started += 1


async def _guarded(semaphore: asyncio.Semaphore, coro_factory, summary: Summary, label: str) -> None:
    async with semaphore:
        try:
            await coro_factory()
        except httpx.TransportError:
            raise
        except Exception as e:  # noqa: BLE001 - one station's failure must not stop the others
            log(f"{label}: error: {e}")
            summary.errors += 1


async def close_stale_cancelling(client, summary: Summary, dry_run: bool, now: datetime) -> None:
    """Force every Cancelling run (any deployment) older than CANCELLING_STALE_MINUTES to Cancelled."""
    runs = await read_all_flow_runs(
        client,
        FlowRunFilter(state=FlowRunFilterState(type=FlowRunFilterStateType(any_=[StateType.CANCELLING]))),
    )
    stale = [r for r in runs if (_age_minutes(_state_since(r), now) or 0) >= CANCELLING_STALE_MINUTES]
    log(
        f"Stale-cancellation sweep: {len(runs)} Cancelling runs, {len(stale)} older than {CANCELLING_STALE_MINUTES:g} min"
    )
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def close(run):
        async with semaphore:
            if await _force_state(client, run, Cancelled(message="watchdog: stale cancellation"), dry_run, "closed"):
                summary.stale_cancels_closed += 1
                summary.closed_ids.add(run.id)
            else:
                summary.errors += 1

    await asyncio.gather(*(close(r) for r in stale))


def select_targets(codes) -> list[str]:
    targets = stations.prefect_run_targets()
    if not codes:
        return targets
    wanted = set(codes)
    selected = [t for t in targets if t.rsplit("/", 1)[1] in wanted]
    unknown = wanted - {t.rsplit("/", 1)[1] for t in selected}
    for code in sorted(unknown):
        log(f"{code}: not an enabled station in config/stations.yaml, skipping")
    return selected


async def run(args) -> Summary:
    summary = Summary()
    now = _now()
    async with get_client() as client:
        error = await client.api_healthcheck()
        if error is not None:
            raise ApiUnreachable(str(error))

        if args.close_stale_cancelling or not args.codes:
            await close_stale_cancelling(client, summary, args.dry_run, now)
        if args.close_stale_cancelling:
            return summary

        semaphore = asyncio.Semaphore(CONCURRENCY)
        await asyncio.gather(
            *(
                _guarded(semaphore, lambda t=t: check_station(client, t, summary, args.dry_run, now), summary, t)
                for t in select_targets(args.codes)
            )
        )
    return summary


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Make sure every enabled station has a live recording flow run.")
    parser.add_argument("--dry-run", action="store_true", help="Log what would change; write nothing")
    parser.add_argument(
        "--codes", nargs="+", metavar="CODE", help="Only check these station codes (skips the global sweep)"
    )
    parser.add_argument(
        "--close-stale-cancelling",
        action="store_true",
        help="Only force stale Cancelling runs (every deployment) to Cancelled, then exit",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        summary = asyncio.run(run(args))
    except (ApiUnreachable, httpx.TransportError) as e:
        log(f"Error connecting to Prefect API: {e}")
        return 1
    prefix = "[dry-run] " if args.dry_run else ""
    log(f"{prefix}Summary: {summary.line()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
