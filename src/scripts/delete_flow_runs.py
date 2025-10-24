#!/usr/bin/env python3

import asyncio
import math
import os
from prefect import get_client
from prefect.client.orchestration import PrefectClient
from prefect.client.schemas.filters import (
    FlowRunFilter,
    FlowRunFilterState,
    FlowRunFilterStateType,
)
from prefect.client.schemas.objects import FlowRun, StateType
from prefect.client.schemas.sorting import FlowRunSort

# Configuration - can be overridden via environment variables
BATCH_SIZE = max(
    1,
    int(os.getenv("BATCH_SIZE", "10")),
)  # Number of concurrent deletions per batch
DELAY_BETWEEN_BATCHES = float(os.getenv("DELAY_BETWEEN_BATCHES", "5.0"))  # Seconds to wait between batches


async def delete_flow_run_safe(client: PrefectClient, run: FlowRun) -> dict:
    base_result = {
        "run_id": str(run.id),
        "run_name": run.name,
    }

    try:
        await client.delete_flow_run(run.id)
        print(f"  ✓ Deleted: {run.name} ({run.id})")
        return {
            **base_result,
            "success": True,
            "error": None,
        }
    except Exception as e:
        print(f"  ✗ Failed: {run.name} ({run.id}) - {str(e)}")
        return {
            **base_result,
            "success": False,
            "error": str(e),
        }


async def delete_flow_runs(state_types: list[StateType]) -> None:
    print(f"Starting deletion process for state types: {state_types}")

    try:
        async with get_client() as client:
            # Get filtered flow runs
            runs = await client.read_flow_runs(
                flow_run_filter=FlowRunFilter(state=FlowRunFilterState(type=FlowRunFilterStateType(any_=state_types))),
                sort=FlowRunSort.START_TIME_ASC,
            )

            if len(runs) == 0:
                print("No flow runs found")
                return

            print(f"Found {len(runs)} flow runs to delete")
            print(f"Using batch size: {BATCH_SIZE}, delay between batches: {DELAY_BETWEEN_BATCHES}s")

            deleted_count = 0
            failed_count = 0
            total_batches = math.ceil(len(runs) / BATCH_SIZE)

            for i in range(0, len(runs), BATCH_SIZE):
                batch = runs[i : i + BATCH_SIZE]
                batch_num = i // BATCH_SIZE + 1

                print(f"Processing batch {batch_num}/{total_batches} ({len(batch)} runs)...")

                # Delete all runs in this batch concurrently
                tasks = [delete_flow_run_safe(client, run) for run in batch]
                results = await asyncio.gather(*tasks)

                # Process results
                batch_success = 0
                batch_failed = 0
                for result in results:
                    if result["success"]:
                        batch_success += 1
                    else:
                        batch_failed += 1

                print(f"Batch {batch_num} completed: {batch_success} succeeded, {batch_failed} failed")
                deleted_count += batch_success
                failed_count += batch_failed

                # Rate limiting between batches
                if i + BATCH_SIZE < len(runs):
                    await asyncio.sleep(DELAY_BETWEEN_BATCHES)

            print("=" * 60)
            print(f"Summary: Successfully deleted {deleted_count}/{len(runs)} flow runs")
            if failed_count > 0:
                print(f"Failed to delete {failed_count} flow runs")

    except Exception as e:
        print(f"Error connecting to Prefect API: {e}")
        exit(1)


if __name__ == "__main__":
    asyncio.run(delete_flow_runs(state_types=[StateType.CANCELLED]))
