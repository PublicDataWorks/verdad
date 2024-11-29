import os
from prefect import Flow
from prefect.tasks import Task
import pytest
from utils import fetch_radio_stations, optional_flow, optional_task

class TestUtils:
    def test_fetch_radio_stations_returns_list(self):
        """Test that fetch_radio_stations returns a list"""
        stations = fetch_radio_stations()
        assert isinstance(stations, list)
        assert len(stations) > 0

    def test_radio_station_structure(self):
        """Test that each radio station has the required fields with correct types"""
        stations = fetch_radio_stations()
        required_fields = {
            'code': str,
            'url': str,
            'state': str,
            'name': str
        }

        for station in stations:
            # Check that all required fields are present
            assert all(field in station for field in required_fields), \
                f"Missing required field(s) in station: {station}"

            # Check field types
            for field, expected_type in required_fields.items():
                assert isinstance(station[field], expected_type), \
                    f"Field '{field}' in station {station['code']} should be {expected_type}"

    def test_unique_station_codes(self):
        """Test that all station codes are unique"""
        stations = fetch_radio_stations()
        codes = [station['code'] for station in stations]
        assert len(codes) == len(set(codes)), "Duplicate station codes found"

    def test_valid_urls(self):
        """Test that all URLs have valid format"""
        stations = fetch_radio_stations()
        for station in stations:
            url = station['url']
            assert url.startswith(('http://', 'https://')), \
                f"Invalid URL format for station {station['code']}: {url}"

    def test_non_empty_fields(self):
        """Test that no fields are empty strings"""
        stations = fetch_radio_stations()
        for station in stations:
            for field, value in station.items():
                assert value.strip() != "", \
                    f"Empty {field} found in station {station['code']}"

    def test_specific_station_exists(self):
        """Test that specific known stations exist in the list"""
        stations = fetch_radio_stations()
        station_codes = [station['code'] for station in stations]

        # Test for a few known station codes
        expected_stations = [
            "WLEL - 94.3 FM",
            "SPMN",
            "WZHF",
            "MCD"
        ]

        for code in expected_stations:
            assert code in station_codes, f"Expected station {code} not found"

    def test_states_are_valid(self):
        """Test that state names are valid"""
        stations = fetch_radio_stations()
        valid_states = {
            "Georgia", "Pennsylvania", "Michigan", "Texas", "Florida",
            "Nevada", "Arizona", "Wisconsin", "Russia", "International"
        }

        for station in stations:
            assert station['state'] in valid_states, \
                f"Invalid state '{station['state']}' for station {station['code']}"

    def test_station_groups(self):
        """Test that the stations can be properly grouped for max and lite recorders"""
        stations = fetch_radio_stations()

        # According to the recording.py file, first 37 stations are for max recorder
        max_recorder_stations = stations[:37]
        lite_recorder_stations = stations[37:]

        assert len(max_recorder_stations) == 37, "Max recorder should have 37 stations"
        assert len(lite_recorder_stations) > 0, "Lite recorder should have some stations"
        assert len(stations) == len(max_recorder_stations) + len(lite_recorder_stations)

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
