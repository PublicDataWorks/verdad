import os
from prefect import Flow
from prefect.tasks import Task
import pytest
from stations import stations_for
from utils import fetch_radio_stations, optional_flow, optional_task


class TestFetchRadioStations:
    """fetch_radio_stations() is now a thin view over config/stations.yaml.

    The station data itself (which recorder serves what, ordering, uniqueness, url hashes) is
    asserted in tests/test_stations.py; these tests only pin the legacy dict shape that
    src/recording.py and the Supabase writes depend on.
    """

    def test_returns_the_direct_stream_stations_in_config_order(self):
        stations = fetch_radio_stations()
        expected = stations_for("max") + stations_for("lite")

        assert isinstance(stations, list)
        assert [s["code"] for s in stations] == [s.code for s in expected]

    def test_station_structure(self):
        """Each station is exactly the four string keys the recorder has always used."""
        for station in fetch_radio_stations():
            assert set(station) == {"code", "url", "state", "name"}
            for field, value in station.items():
                assert isinstance(value, str), f"Field '{field}' in {station['code']} should be a str"
                assert value.strip() != "", f"Empty {field} found in station {station['code']}"

    def test_excludes_generic_stations(self):
        """The browser-driven stations are served by generic_recording.py, not by this list."""
        codes = {station["code"] for station in fetch_radio_stations()}
        for station in stations_for("generic"):
            assert station.code not in codes

    def test_unique_station_codes(self):
        codes = [station["code"] for station in fetch_radio_stations()]
        assert len(codes) == len(set(codes)), "Duplicate station codes found"

    def test_valid_urls(self):
        for station in fetch_radio_stations():
            assert station["url"].startswith(("http://", "https://")), (
                f"Invalid URL format for station {station['code']}: {station['url']}"
            )

    def test_specific_station_exists(self):
        codes = [station["code"] for station in fetch_radio_stations()]
        for code in ["WLEL - 94.3 FM", "SPMN", "WZHF", "MCD"]:
            assert code in codes, f"Expected station {code} not found"


class TestOptionalDecorators:
    def test_optional_task_basic(self):
        """Test optional_task with basic syntax @optional_task"""
        @optional_task
        def func():
            return "test"

        assert func() == "test"

    def test_optional_task_with_params(self):
        """Test optional_task with parameters @optional_task(param=value)"""
        @optional_task(log_prints=True)
        def func():
            return "test"

        assert func() == "test"

    def test_optional_task_with_multiple_params(self):
        """Test optional_task with multiple parameters"""
        @optional_task(log_prints=True, retries=10)
        def func():
            return "test"

        assert func() == "test"

    def test_optional_task_preserves_function_metadata(self):
        """Test that optional_task preserves function metadata"""
        @optional_task
        def func(x: int, y: str = "default") -> str:
            """Test function docstring"""
            return f"{x} {y}"

        # Check if type hints are preserved
        assert func.__annotations__ == {'x': int, 'y': str, 'return': str}
        # Check if docstring is preserved
        assert func.__doc__ == "Test function docstring"
        # Check if function name is preserved
        assert func.__name__ == "func"
        # Check if function still works
        assert func(1, "test") == "1 test"
        assert func(1) == "1 default"

    def test_optional_task_with_args_kwargs(self):
        """Test optional_task with both args and kwargs"""
        @optional_task(log_prints=True)
        def func(*args, **kwargs):
            return args, kwargs

        assert func(1, 2, x=3) == ((1, 2), {'x': 3})

    def test_optional_flow_basic(self):
        """Test optional_flow with basic syntax @optional_flow"""
        @optional_flow
        def func():
            return "test"

        assert func() == "test"

    def test_optional_flow_with_params(self):
        """Test optional_flow with parameters @optional_flow(param=value)"""
        @optional_flow(name="test_flow", log_prints=True)
        def func():
            return "test"

        assert func() == "test"

    def test_optional_flow_with_multiple_params(self):
        """Test optional_flow with multiple parameters"""
        @optional_flow(
            name="test_flow",
            log_prints=True,
            retries=10,
            task_runner=None
        )
        def func():
            return "test"

        assert func() == "test"

    def test_optional_flow_preserves_function_metadata(self):
        """Test that optional_flow preserves function metadata"""
        @optional_flow
        def func(x: int, y: str = "default") -> str:
            """Test flow docstring"""
            return f"{x} {y}"

        # Check if type hints are preserved
        assert func.__annotations__ == {'x': int, 'y': str, 'return': str}
        # Check if docstring is preserved
        assert func.__doc__ == "Test flow docstring"
        # Check if function name is preserved
        assert func.__name__ == "func"
        # Check if function still works
        assert func(1, "test") == "1 test"
        assert func(1) == "1 default"

    def test_optional_flow_with_args_kwargs(self):
        """Test optional_flow with both args and kwargs"""
        @optional_flow(name="test_flow")
        def func(*args, **kwargs):
            return args, kwargs

        assert func(1, 2, x=3) == ((1, 2), {'x': 3})

    def test_optional_flow_with_nested_tasks(self):
        """Test optional_flow with nested task calls"""
        @optional_task
        def task1(x):
            return x * 2

        @optional_task
        def task2(x):
            return x + 1

        @optional_flow
        def workflow(x):
            a = task1(x)
            return task2(a)

        assert workflow(2) == 5

    def test_prefect_enabled_task(self):
        """Test behavior when Prefect decorator is enabled for tasks"""
        # Temporarily enable Prefect decorator
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'true'
        try:
            @optional_task(log_prints=True)
            def func():
                return "test"

            # Verify that the function is wrapped with Prefect task
            assert isinstance(func, Task)
        finally:
            # Reset to disabled
            os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

    def test_prefect_enabled_flow(self):
        """Test behavior when Prefect decorator is enabled for flows"""
        # Temporarily enable Prefect decorator
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'true'
        try:
            @optional_flow(name="test_flow")
            def func():
                return "test"

            # Verify that the function is wrapped with Prefect flow
            assert isinstance(func, Flow)
        finally:
            # Reset to disabled
            os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

    def test_prefect_disabled_task(self):
        """Test behavior when Prefect decorator is explicitly disabled for tasks"""
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

        @optional_task
        def func():
            return "test"

        # Verify that the function is not wrapped
        assert not isinstance(func, Task)
        assert callable(func)
        assert func() == "test"

    def test_prefect_disabled_flow(self):
        """Test behavior when Prefect decorator is explicitly disabled for flows"""
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

        @optional_flow
        def func():
            return "test"

        # Verify that the function is not wrapped
        assert not isinstance(func, Flow)
        assert callable(func)
        assert func() == "test"

    def test_optional_decorators_environment_sensitivity(self):
        """Test that decorators respond correctly to environment changes"""
        # Test with Prefect enabled
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'true'

        @optional_task
        def task_func():
            return "task"

        @optional_flow
        def flow_func():
            return "flow"

        assert isinstance(task_func, Task)
        assert isinstance(flow_func, Flow)

        # Test with Prefect disabled
        os.environ['ENABLE_PREFECT_DECORATOR'] = 'false'

        @optional_task
        def task_func2():
            return "task"

        @optional_flow
        def flow_func2():
            return "flow"

        assert not isinstance(task_func2, Task)
        assert not isinstance(flow_func2, Flow)
        assert task_func2() == "task"
        assert flow_func2() == "flow"

    def test_optional_flow_error_handling(self):
        """Test error handling in flows"""
        @optional_flow
        def error_flow():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            error_flow()

    def test_optional_flow_with_complex_return_types(self):
        """Test flows with complex return types"""
        @optional_flow
        def complex_flow():
            return {
                "list": [1, 2, 3],
                "dict": {"a": 1},
                "tuple": (1, 2),
                "set": {1, 2, 3}
            }

        result = complex_flow()
        assert isinstance(result, dict)
        assert result["list"] == [1, 2, 3]
        assert result["dict"] == {"a": 1}
        assert result["tuple"] == (1, 2)
        assert result["set"] == {1, 2, 3}
