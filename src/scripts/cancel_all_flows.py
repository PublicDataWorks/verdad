#!/usr/bin/env python3

import asyncio
from prefect import get_client
from prefect.client.schemas.filters import (
    FlowRunFilter,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import StateType
from prefect.states import Cancelled


async def cancel_all_runs():
    try:
        async with get_client() as client:
            # Get all running and pending flows
            runs = await client.read_flow_runs(
                flow_run_filter=FlowRunFilter(
                    state=FlowRunFilterState(
                        type=FlowRunFilterStateType(
                            any_=[
                                StateType.RUNNING,
                                StateType.PENDING,
                            ]
                        )
                    )
                )
            )

            cancelled_count = 0
            failed_count = 0

            for run in runs:
                try:
                    await client.set_flow_run_state(
                        run.id,
                        state=Cancelled(message="Cancelled by scheduled restart"),
                    )
                    print(f"- Cancelled: {run.name} ({run.id})")
                    cancelled_count += 1
                except Exception as e:
                    print(f"- Failed to cancel {run.name} ({run.id}): {e}")
                    failed_count += 1

            print(f"\nSummary: Successfully cancelled {cancelled_count} flow runs")
            if failed_count > 0:
                print(f"Failed to cancel {failed_count} flow runs")
            if len(runs) == 0:
                print("No running flow runs found")

    except Exception as e:
        print(f"Error connecting to Prefect API: {e}")
        exit(1)


if __name__ == "__main__":
    asyncio.run(cancel_all_runs())
