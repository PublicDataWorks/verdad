import os
from prefect import flow, task
from prefect.cache_policies import NO_CACHE

from stations import station_dicts


def optional_task(func=None, **kwargs):
    """Decorator that applies Prefect task decorator unless explicitly disabled

    Supports both @optional_task and @optional_task(param=value) syntax

    The decorator is enabled by default and can be disabled by setting
    ENABLE_PREFECT_DECORATOR=false in environment variables.

    Args:
        func: The function to decorate (provided automatically when used as @optional_task)
        **kwargs: Variable keyword arguments to pass to Prefect task

    Returns:
        Function: Original function if Prefect decorator is disabled,
                 or Prefect task-decorated function if enabled
    """
    enable_prefect = os.getenv("ENABLE_PREFECT_DECORATOR", "true").lower() == "true"

    if not enable_prefect:
        # If Prefect decorator is disabled, return the function as-is
        def wrapper(f):
            return f

    else:
        # If Prefect decorator is enabled (default), apply Prefect task decorator
        if "cache_policy" not in kwargs:
            kwargs["cache_policy"] = NO_CACHE

        if "cache_result_in_memory" not in kwargs:
            kwargs["cache_result_in_memory"] = False

        def wrapper(f):
            return task(**kwargs)(f)

    # Handle both @optional_task and @optional_task() syntax
    if func is not None and callable(func):
        # @optional_task
        return wrapper(func)
    # @optional_task(param=value)
    return wrapper


def optional_flow(func=None, **kwargs):
    """Decorator that applies Prefect flow decorator unless explicitly disabled

    Supports both @optional_flow and @optional_flow(param=value) syntax

    The decorator is enabled by default and can be disabled by setting
    ENABLE_PREFECT_DECORATOR=false in environment variables.

    Args:
        func: The function to decorate (provided automatically when used as @optional_flow)
        **kwargs: Variable keyword arguments to pass to Prefect flow

    Returns:
        Function: Original function if Prefect decorator is disabled,
                 or Prefect flow-decorated function if enabled
    """
    enable_prefect = os.getenv("ENABLE_PREFECT_DECORATOR", "true").lower() == "true"

    if not enable_prefect:
        # If Prefect decorator is disabled, return the function as-is
        def wrapper(f):
            return f

    else:
        # If Prefect decorator is enabled (default), apply Prefect flow decorator
        def wrapper(f):
            return flow(**kwargs)(f)

    # Handle both @optional_flow and @optional_flow() syntax
    if func is not None and callable(func):
        # @optional_flow
        return wrapper(func)
    # @optional_flow(param=value)
    return wrapper


def fetch_radio_stations():
    """The direct-stream (max + lite) stations as legacy four-key dicts, in config file order.

    Station data lives in config/stations.yaml; see src/stations.py.
    """
    return station_dicts()
