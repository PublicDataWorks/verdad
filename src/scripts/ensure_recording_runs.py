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

- leaves the deployment alone if it has a Scheduled (including Late) run; one older than
  ``SCHEDULED_STALE_MINUTES`` is logged as a warning, because it means no worker is picking it up and
  another run would only queue behind it;
- treats a Pending run as on its way up, unless it has been Pending for ``PENDING_STALE_MINUTES``
  (the runner that took it is gone): then it is set to Cancelling;
- treats a Running run as healthy if it started, or its newest task run started, within
  ``RUNNING_IDLE_MINUTES``; any other Running run is a zombie and is set to **Cancelling**, not
  Crashed. The serve() Runner kills a flow's process only when it sees Cancelling, so if the
  watchdog misjudged a live run, Cancelling stops it, whereas a forced Crashed would leave it
  recording next to its replacement (two recorders, duplicate audio_files rows);
- forces Cancelling runs older than ``CANCELLING_STALE_MINUTES`` to Cancelled (their worker is gone, so
  cancellation never completes);
- creates one new flow run when no healthy run remains and nothing is on its way out. A zombie or
  stale Pending run set to Cancelling this tick, or a Cancelling run younger than
  ``CANCELLING_STALE_MINUTES``, defers the new run: a later tick closes the cancellation and starts
  the replacement. Recovery is therefore about one tick (15 min) when no run exists and up to about
  70 min when a zombie is left Running (45 min idle + one 10-min Cancelling close + one tick).

After the per-station checks, a normal run (no ``--codes``) sweeps every deployment, processing ones
included, for stale Cancelling runs so ``delete_flow_runs.py`` can delete them; a failure there is
logged and counted, never fatal. ``--close-stale-cancelling`` does only that sweep.

Every state write checks the ``OrchestrationResult`` it gets back: only ACCEPT counts as done;
REJECT/ABORT/WAIT are logged and counted as ``rejected``.

Locking: the script takes ``flock(LOCK_EX | LOCK_NB)`` on ``$RECORDING_LOCK_FILE`` (default
``/tmp/verdad-recording.lock``), the lock restart_all.sh holds for the whole restart. If it is held
the tick is skipped with exit 0, so a manual run cannot overlap a restart either.

Sentry (only when ``SENTRY_DSN`` is set and not ``--dry-run``): an error event when the API is
unreachable or any per-station or sweep step failed or was rejected, fingerprinted per UTC hour; and,
for full runs (no ``--codes``/``--close-stale-cancelling``), a Crons check-in with slug
``recording-watchdog`` so Sentry notices when the cron stops running the watchdog at all.

Exit status: 0 = ran cleanly (or skipped for the lock), 1 = Prefect API unreachable at the start,
2 = the run finished but some steps failed or were rejected.
"""

import argparse
import asyncio
import fcntl
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

from prefect import get_client  # noqa: E402
from prefect.client.schemas.filters import (  # noqa: E402
    FlowRunFilter,
    FlowRunFilterDeploymentId,
    FlowRunFilterId,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import StateType  # noqa: E402
from prefect.client.schemas.responses import SetStateStatus  # noqa: E402
from prefect.client.schemas.sorting import FlowRunSort, TaskRunSort  # noqa: E402
from prefect.exceptions import ObjectNotFound  # noqa: E402
from prefect.states import Cancelled, Cancelling  # noqa: E402

import stations  # noqa: E402

try:  # sentry-sdk is in the prefect image; keep the script usable (and testable) without it.
    import sentry_sdk
    import sentry_sdk.crons
except ImportError:  # only where sentry-sdk is absent
    sentry_sdk = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


SCHEDULED_STALE_MINUTES = _env_float("WATCHDOG_SCHEDULED_STALE_MINUTES", 30)
PENDING_STALE_MINUTES = _env_float("WATCHDOG_PENDING_STALE_MINUTES", 10)
RUNNING_IDLE_MINUTES = _env_float("WATCHDOG_RUNNING_IDLE_MINUTES", 45)
CANCELLING_STALE_MINUTES = _env_float("WATCHDOG_CANCELLING_STALE_MINUTES", 10)
CONCURRENCY = max(1, int(_env_float("WATCHDOG_CONCURRENCY", 8)))
DEFAULT_LOCK_FILE = "/tmp/verdad-recording.lock"
# The Prefect server rejects /flow_runs/filter with limit > 200.
PAGE_SIZE = 200

MONITOR_SLUG = "recording-watchdog"
MONITOR_CONFIG = {
    "schedule": {"type": "crontab", "value": "7,22,37,52 * * * *"},
    "timezone": "UTC",
    "checkin_margin": 5,
    "max_runtime": 10,
}
FLUSH_TIMEOUT_SECONDS = 30

ACTIVE_STATES = [StateType.SCHEDULED, StateType.PENDING, StateType.RUNNING, StateType.CANCELLING]

EXIT_OK = 0
EXIT_UNREACHABLE = 1
EXIT_ERRORS = 2


class ApiUnreachable(Exception):
    """The Prefect API could not be reached at the start of the run."""


@dataclass
class Summary:
    checked: int = 0
    healthy: int = 0
    started: int = 0
    zombies_cancelled: int = 0
    stale_pending_cancelled: int = 0
    stale_cancels_closed: int = 0
    deferred: int = 0
    missing: int = 0
    rejected: int = 0
    errors: int = 0
    # Runs already closed this tick, so the sweep after the station checks does not count them twice.
    closed_ids: set = field(default_factory=set)

    @property
    def failures(self) -> int:
        return self.errors + self.rejected

    def line(self) -> str:
        return (
            f"checked={self.checked} healthy={self.healthy} started={self.started} "
            f"zombies_cancelled={self.zombies_cancelled} stale_pending_cancelled={self.stale_pending_cancelled} "
            f"stale_cancels_closed={self.stale_cancels_closed} deferred={self.deferred} missing={self.missing} "
            f"rejected={self.rejected} errors={self.errors}"
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


async def _set_state(client, run, state, summary: Summary, dry_run: bool, label: str, force: bool) -> bool:
    """Propose `state` for `run`; True only when the server ACCEPTed it.

    A non-ACCEPT result is counted in summary.rejected and an exception in summary.errors; neither
    stops the caller.
    """
    if dry_run:
        log(f"  [dry-run] would set {run.name} ({run.id}) to {state.name}: {state.message}")
        return True
    try:
        result = await client.set_flow_run_state(run.id, state=state, force=force)
    except Exception as e:  # noqa: BLE001 - log and keep going; one bad run must not stop the others
        log(f"  failed to set {run.name} ({run.id}) to {state.name}: {type(e).__name__}: {e}")
        summary.errors += 1
        return False
    status = getattr(result, "status", None)
    if status == SetStateStatus.ACCEPT:
        log(f"  {label}: {run.name} ({run.id}) -> {state.name}")
        return True
    reason = getattr(getattr(result, "details", None), "reason", None)
    status_name = getattr(status, "value", status)
    log(f"  {label} NOT applied: {run.name} ({run.id}) -> {state.name} was {status_name}: {reason or 'no reason'}")
    summary.rejected += 1
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

    scheduled = [r for r in runs if r.state_type == StateType.SCHEDULED]
    pending = [r for r in runs if r.state_type == StateType.PENDING]
    running = [r for r in runs if r.state_type == StateType.RUNNING]
    cancelling = [r for r in runs if r.state_type == StateType.CANCELLING]

    healthy = False
    # Anything set to Cancelling this tick, or still Cancelling, is on its way out: a replacement waits
    # for a later tick so a misjudged live run is stopped before a second recorder starts.
    in_transition = False

    for run in scheduled:
        age = _age_minutes(run.created, now)
        if age is not None and age >= SCHEDULED_STALE_MINUTES:
            state_name = run.state.name if run.state else run.state_type.value
            log(
                f"{target}: WARNING {state_name} run {run.name} ({run.id}) is {age:.0f} min old; no worker is picking it up"
            )
        healthy = True

    for run in pending:
        age = _age_minutes(_state_since(run), now)
        if age is None or age < PENDING_STALE_MINUTES:
            healthy = True
            continue
        log(f"{target}: run {run.name} ({run.id}) has been Pending for {age:.0f} min")
        in_transition = True
        if await _set_state(
            client,
            run,
            Cancelling(message=f"watchdog: stuck in Pending for {int(age)} min"),
            summary,
            dry_run,
            "cancelling stale Pending run",
            force=False,
        ):
            summary.stale_pending_cancelled += 1

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
        in_transition = True
        if await _set_state(
            client,
            run,
            Cancelling(message=f"watchdog: no task activity for {idle_minutes} min"),
            summary,
            dry_run,
            "cancelling zombie",
            force=False,
        ):
            summary.zombies_cancelled += 1

    for run in cancelling:
        age = _age_minutes(_state_since(run), now)
        if age is not None and age >= CANCELLING_STALE_MINUTES:
            if await _set_state(
                client,
                run,
                Cancelled(message="watchdog: stale cancellation"),
                summary,
                dry_run,
                "closed stale cancellation",
                force=True,
            ):
                summary.stale_cancels_closed += 1
                summary.closed_ids.add(run.id)
            else:
                in_transition = True
        else:
            in_transition = True

    if healthy:
        summary.healthy += 1
        return
    if in_transition:
        log(f"{target}: a run is on its way out; deferring a new run to the next tick")
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
        except Exception as e:  # noqa: BLE001 - one station's failure (5xx, timeout, ...) must not stop the others
            log(f"{label}: error: {type(e).__name__}: {e}")
            summary.errors += 1


async def close_stale_cancelling(client, summary: Summary, dry_run: bool, now: datetime) -> None:
    """Force every Cancelling run (any deployment) older than CANCELLING_STALE_MINUTES to Cancelled."""
    runs = await read_all_flow_runs(
        client,
        FlowRunFilter(state=FlowRunFilterState(type=FlowRunFilterStateType(any_=[StateType.CANCELLING]))),
    )
    stale = [
        r
        for r in runs
        if r.id not in summary.closed_ids and (_age_minutes(_state_since(r), now) or 0) >= CANCELLING_STALE_MINUTES
    ]
    log(
        f"Stale-cancellation sweep: {len(runs)} Cancelling runs, {len(stale)} older than {CANCELLING_STALE_MINUTES:g} min"
    )
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def close(run):
        async with semaphore:
            if await _set_state(
                client, run, Cancelled(message="watchdog: stale cancellation"), summary, dry_run, "closed", force=True
            ):
                summary.stale_cancels_closed += 1
                summary.closed_ids.add(run.id)

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
    reached = False
    try:
        async with get_client() as client:
            error = await client.api_healthcheck()
            if error is not None:
                raise ApiUnreachable(f"{type(error).__name__}: {error}")
            reached = True

            if not args.close_stale_cancelling:
                semaphore = asyncio.Semaphore(CONCURRENCY)
                await asyncio.gather(
                    *(
                        _guarded(
                            semaphore, lambda t=t: check_station(client, t, summary, args.dry_run, now), summary, t
                        )
                        for t in select_targets(args.codes)
                    )
                )

            if args.close_stale_cancelling or not args.codes:
                try:
                    await close_stale_cancelling(client, summary, args.dry_run, now)
                except Exception as e:  # noqa: BLE001 - the sweep is housekeeping; never abort the tick for it
                    log(f"Stale-cancellation sweep failed: {type(e).__name__}: {e}")
                    summary.errors += 1
    except ApiUnreachable:
        raise
    except Exception as e:
        if not reached:  # opening the client failed before the health check could run
            raise ApiUnreachable(f"{type(e).__name__}: {e}") from e
        raise
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


def lock_file_path() -> str:
    return os.getenv("RECORDING_LOCK_FILE") or DEFAULT_LOCK_FILE


def acquire_lock(path: str):
    """Non-blocking exclusive flock on `path`; the open fd while held, None when someone else holds it."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def _hour_key(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H")


def _report_to_sentry(message: str, extra: dict) -> None:
    sentry_sdk.capture_event(
        {
            "message": f"Recording watchdog: {message}",
            "level": "error",
            "tags": {"check": "recording_watchdog"},
            "extra": extra,
            "fingerprint": [MONITOR_SLUG, "errors", _hour_key(_now())],
        }
    )


def _watch(args, sentry_on: bool) -> int:
    """Take the lock, run one tick, report. Returns the exit status."""
    path = lock_file_path()
    fd = acquire_lock(path)
    if fd is None:
        log("watchdog: restart in progress, skipping tick")
        return EXIT_OK
    try:
        try:
            summary = asyncio.run(run(args))
        except ApiUnreachable as e:
            log(f"Error connecting to Prefect API: {e}")
            if sentry_on:
                _report_to_sentry(f"Prefect API unreachable: {e}", {"error": str(e)})
            return EXIT_UNREACHABLE
    finally:
        os.close(fd)

    prefix = "[dry-run] " if args.dry_run else ""
    log(f"{prefix}Summary: {summary.line()}")
    if summary.failures:
        if sentry_on:
            _report_to_sentry(
                f"{summary.errors} errors, {summary.rejected} rejected state changes",
                {"summary": summary.line()},
            )
        return EXIT_ERRORS
    return EXIT_OK


class _CheckinFailed(Exception):
    """Raised inside the Crons context so a failed tick checks in as an error."""


def main(argv=None) -> int:
    args = parse_args(argv)
    dsn = os.getenv("SENTRY_DSN") or None
    sentry_on = bool(dsn) and sentry_sdk is not None and not args.dry_run
    if not sentry_on:
        return _watch(args, sentry_on=False)

    sentry_sdk.init(dsn=dsn)
    # Only full ticks check in: a manual --codes or --close-stale-cancelling run is not the cron.
    full_tick = not args.codes and not args.close_stale_cancelling
    code = EXIT_ERRORS
    try:
        if full_tick:
            with sentry_sdk.crons.monitor(monitor_slug=MONITOR_SLUG, monitor_config=MONITOR_CONFIG):
                code = _watch(args, sentry_on=True)
                if code != EXIT_OK:
                    raise _CheckinFailed(code)
        else:
            code = _watch(args, sentry_on=True)
    except _CheckinFailed:
        pass
    finally:
        sentry_sdk.flush(timeout=FLUSH_TIMEOUT_SECONDS)
    return code


if __name__ == "__main__":
    sys.exit(main())
