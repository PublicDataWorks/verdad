import os
from prefect.tasks import Task
from utils import fetch_radio_stations, optional_task

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

    def test_prefect_enabled(self):
        """Test behavior when Prefect decorator is enabled"""
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
