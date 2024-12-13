import os
import subprocess
import pytest
from unittest.mock import Mock, patch, call

# Set environment variable before importing RadioStation
os.environ["ENABLE_PREFECT_DECORATOR"] = "false"
from radiostations.base import RadioStation


class TestRadioStation:
    @pytest.fixture
    def radio_station(self):
        """Create a test radio station instance"""
        return RadioStation(
            url="https://test.radio/stream",
            sink_name="test_sink",
            source_name="test_source",
            play_button_selector="button.play",
            video_element_selector="video.player",
        )

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess for testing"""
        with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
            mock_run.return_value = Mock(stdout="123\n", stderr="", check=True)
            yield {
                "run": mock_run,
                "popen": mock_popen,
                "called_process_error": subprocess.CalledProcessError(returncode=1, cmd=["pulseaudio", "--check"]),
            }

    @pytest.fixture
    def mock_webdriver(self):
        """Mock Selenium WebDriver"""
        with patch("selenium.webdriver.Chrome") as mock_chrome, patch(
            "selenium.webdriver.chrome.service.Service"
        ) as mock_service, patch("webdriver_manager.chrome.ChromeDriverManager") as mock_manager:
            mock_driver = Mock()
            mock_chrome.return_value = mock_driver
            yield {"chrome": mock_chrome, "service": mock_service, "manager": mock_manager, "driver": mock_driver}

    def test_init(self, radio_station):
        """Test RadioStation initialization"""
        assert radio_station.url == "https://test.radio/stream"
        assert radio_station.sink_name == "test_sink"
        assert radio_station.source_name == "test_source"
        assert radio_station.play_button_selector == "button.play"
        assert radio_station.video_element_selector == "video.player"
        assert radio_station.driver is None
        assert radio_station.sink_module is None
        assert radio_station.source_module is None

    def test_setup_virtual_audio_success(self, radio_station, mock_subprocess):
        """Test successful virtual audio setup"""
        # Mock ensure_pulseaudio_running to avoid actual system calls
        with patch.object(radio_station, "ensure_pulseaudio_running"):
            radio_station.setup_virtual_audio()

            # Verify all the subprocess.run calls with exact command format
            assert mock_subprocess["run"].call_args_list == [
                # First call: load sink module
                call(
                    [
                        "pactl",
                        "load-module",
                        "module-null-sink",
                        f"sink_name={radio_station.sink_name}",
                        f"sink_properties=device.description={radio_station.sink_name}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ),
                # Second call: load source module
                call(
                    [
                        "pactl",
                        "load-module",
                        "module-virtual-source",
                        f"source_name={radio_station.source_name}",
                        f"master={radio_station.sink_name}.monitor",
                        f"source_properties=device.description={radio_station.source_name}",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ),
                # Third call: set sink to running state
                call(["pactl", "suspend-sink", radio_station.sink_name, "0"], check=True),
                # Fourth call: set source to running state
                call(["pactl", "suspend-source", radio_station.source_name, "0"], check=True),
            ]

            # Verify the module IDs were stored
            assert radio_station.sink_module == "123"
            assert radio_station.source_module == "123"

    def test_setup_virtual_audio_failure(self, radio_station, mock_subprocess):
        """Test virtual audio setup failure"""
        error = subprocess.CalledProcessError(returncode=1, cmd=["pactl", "load-module"])
        mock_subprocess["run"].side_effect = error

        # Mock ensure_pulseaudio_running to avoid actual system calls
        with patch.object(radio_station, "ensure_pulseaudio_running"):
            with pytest.raises(subprocess.CalledProcessError) as exc_info:
                radio_station.setup_virtual_audio()

            assert exc_info.value.returncode == 1
            assert exc_info.value.cmd == ["pactl", "load-module"]

    @patch("time.sleep")
    @patch("radiostations.base.WebDriverWait")
    def test_start_browser_success(self, mock_wait, mock_sleep, radio_station, mock_webdriver):
        """Test successful browser start"""
        # Setup mocks
        mock_element = Mock()
        mock_webdriver["driver"].find_element.return_value = mock_element
        mock_webdriver["driver"].execute_script.return_value = True

        # Setup WebDriverWait mock
        mock_wait_instance = Mock()
        mock_wait.return_value = mock_wait_instance
        mock_wait_instance.until.return_value = mock_element

        radio_station.start_browser()

        # Verify driver setup
        assert radio_station.driver == mock_webdriver["driver"]

        # Verify Chrome options
        chrome_options_calls = mock_webdriver["chrome"].call_args[1]["options"]
        expected_arguments = [
            "--headless",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--use-pulse-audio",
            "--autoplay-policy=no-user-gesture-required",
        ]
        for arg in expected_arguments:
            assert arg in chrome_options_calls.arguments

        # Verify URL navigation
        mock_webdriver["driver"].get.assert_called_with(radio_station.url)

        # Verify wait and click sequence
        mock_wait.assert_called_with(mock_webdriver["driver"], 10)
        mock_wait_instance.until.assert_called()
        mock_element.click.assert_called_once()

        # Verify sleep calls
        assert mock_sleep.call_count == 2
        mock_sleep.assert_has_calls([call(5), call(30)])

    @patch("time.sleep")
    def test_start_playing_success(self, mock_sleep, radio_station, mock_webdriver):
        """Test successful playback start"""
        radio_station.driver = mock_webdriver["driver"]
        mock_element = Mock()
        mock_webdriver["driver"].find_element.return_value = mock_element
        mock_webdriver["driver"].execute_script.return_value = True

        radio_station.start_playing()

        assert mock_element.click.called

    @patch("time.sleep")
    def test_start_playing_failure(self, mock_sleep, radio_station, mock_webdriver):
        """Test playback start failure"""
        radio_station.driver = mock_webdriver["driver"]
        mock_webdriver["driver"].execute_script.return_value = False

        with pytest.raises(Exception, match=f"Failed to start audio for {radio_station.url}"):
            radio_station.start_playing()

    def test_is_audio_playing_success(self, radio_station, mock_subprocess):
        """Test audio playing check success"""
        mock_subprocess["run"].return_value.stdout = f"State: RUNNING\nName: {radio_station.sink_name}"

        assert radio_station.is_audio_playing() is True

    def test_is_audio_playing_failure(self, radio_station, mock_subprocess):
        """Test audio playing check failure"""
        mock_subprocess["run"].return_value.stdout = f"State: SUSPENDED\nName: {radio_station.sink_name}"

        assert radio_station.is_audio_playing() is False

    def test_stop(self, radio_station, mock_subprocess):
        """Test radio station stop"""
        radio_station.driver = Mock()
        radio_station.sink_module = "123"
        radio_station.source_module = "456"

        # Mock the module existence check
        mock_subprocess["run"].return_value.stdout = "123\n456"

        radio_station.stop()

        assert radio_station.driver.quit.called
        assert mock_subprocess["run"].call_count >= 2

    def test_ensure_pulseaudio_running_already_running(self, radio_station, mock_subprocess):
        """Test PulseAudio check when already running"""
        radio_station.ensure_pulseaudio_running()

        assert mock_subprocess["run"].called
        assert not mock_subprocess["popen"].called

    def test_ensure_pulseaudio_running_needs_start(self, radio_station, mock_subprocess):
        """Test PulseAudio start when not running"""
        # First call raises CalledProcessError, second call returns None
        error = subprocess.CalledProcessError(returncode=1, cmd=["pulseaudio", "--check"])
        mock_subprocess["run"].side_effect = [
            error,  # First check fails
            None,  # Second check passes
        ]

        # Mock time.sleep to avoid actual delays
        with patch("time.sleep"):
            radio_station.ensure_pulseaudio_running()

        # Verify that Popen was called with correct arguments
        mock_subprocess["popen"].assert_called_once_with(
            ["pulseaudio", "--start", "--log-target=stderr", "--exit-idle-time=-1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Verify that run was called twice
        assert mock_subprocess["run"].call_count == 2
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pulseaudio", "--check"], check=True),  # First check (fails)
                call(["pulseaudio", "--check"], check=True),  # Second check (passes)
            ]
        )

    def test_ensure_pulseaudio_running_failure(self, radio_station, mock_subprocess):
        """Test PulseAudio start failure"""
        error = subprocess.CalledProcessError(returncode=1, cmd=["pulseaudio", "--check"])
        # Make all run calls fail
        mock_subprocess["run"].side_effect = error

        # Mock time.sleep to avoid actual delays
        with patch("time.sleep"):
            with pytest.raises(Exception, match="Failed to start PulseAudio."):
                radio_station.ensure_pulseaudio_running()

        # Verify that both the initial check and the verification check were attempted
        assert mock_subprocess["run"].call_count == 2
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pulseaudio", "--check"], check=True),  # First check
                call(["pulseaudio", "--check"], check=True),  # Second check
            ]
        )

        # Verify that Popen was called to attempt starting PulseAudio
        mock_subprocess["popen"].assert_called_once_with(
            ["pulseaudio", "--start", "--log-target=stderr", "--exit-idle-time=-1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def test_execute_command_success(self, radio_station, mock_subprocess):
        """Test command execution success"""
        mock_subprocess["run"].return_value.stdout = "test output"

        radio_station.execute_command(["test", "command"])

        assert mock_subprocess["run"].called

    def test_execute_command_failure(self, radio_station, mock_subprocess):
        """Test command execution failure"""
        mock_subprocess["run"].side_effect = Exception("Command failed")

        radio_station.execute_command(["test", "command"])
        # Should not raise exception, just print error message

    def test_is_audio_playing_success(self, radio_station, mock_subprocess):
        """Test audio playing check success"""
        mock_subprocess[
            "run"
        ].return_value.stdout = f"""
            Sink #0
            State: RUNNING
            Name: {radio_station.sink_name}
            Description: Test Sink
        """

        assert radio_station.is_audio_playing() is True

    def test_is_audio_playing_failure_sink_not_found(self, radio_station, mock_subprocess):
        """Test audio playing check when sink is not found"""
        mock_subprocess["run"].return_value.stdout = "State: RUNNING\nName: different_sink"

        assert radio_station.is_audio_playing() is False

    def test_is_audio_playing_failure_not_running(self, radio_station, mock_subprocess):
        """Test audio playing check when sink is not running"""
        mock_subprocess[
            "run"
        ].return_value.stdout = f"""
            State: SUSPENDED
            Name: {radio_station.sink_name}
        """

        assert radio_station.is_audio_playing() is False

    def test_is_audio_playing_command_error(self, radio_station, mock_subprocess):
        """Test audio playing check when command fails"""
        mock_subprocess["run"].side_effect = subprocess.CalledProcessError(1, ["pactl", "list", "sinks"])

        assert radio_station.is_audio_playing() is False

    def test_stop_with_driver(self, radio_station, mock_subprocess):
        """Test stop with driver"""
        radio_station.driver = Mock()
        radio_station.sink_module = "123"
        radio_station.source_module = "456"

        # Mock the module existence check
        mock_subprocess["run"].return_value = Mock(stdout="123\n456", stderr="", check=True)

        radio_station.stop()

        # Verify driver quit was called
        radio_station.driver.quit.assert_called_once()

        # Verify all subprocess calls in order
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "123"], check=True),
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "456"], check=True),
            ]
        )

    def test_stop_without_driver(self, radio_station, mock_subprocess):
        """Test stop without driver"""
        radio_station.driver = None
        radio_station.sink_module = "123"
        radio_station.source_module = "456"

        # Mock the module existence check
        mock_subprocess["run"].return_value = Mock(stdout="123\n456", stderr="", check=True)

        radio_station.stop()

        # Verify all subprocess calls in order
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "123"], check=True),
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "456"], check=True),
            ]
        )

    def test_stop_module_already_unloaded(self, radio_station, mock_subprocess):
        """Test stop when modules are already unloaded"""
        radio_station.driver = None
        radio_station.sink_module = "123"
        radio_station.source_module = "456"

        # Mock the module list to show modules don't exist
        mock_subprocess["run"].return_value = Mock(stdout="789\n012", stderr="", check=True)

        radio_station.stop()

        # Verify list checks were made for both modules
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
            ]
        )

    def test_stop_unload_error(self, radio_station, mock_subprocess):
        """Test stop when unload command fails"""
        radio_station.driver = None
        radio_station.sink_module = "123"
        radio_station.source_module = "456"

        # Setup mock responses
        list_modules_response = Mock(stdout="123\n456", stderr="", check=True)
        error = subprocess.CalledProcessError(1, ["pactl", "unload-module", "123"])

        mock_subprocess["run"].side_effect = [
            list_modules_response,  # First list modules check
            error,  # First unload attempt fails
            list_modules_response,  # Second list modules check
            None,  # Second unload succeeds
        ]

        radio_station.stop()

        # Verify the expected sequence of calls
        mock_subprocess["run"].assert_has_calls(
            [
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "123"], check=True),
                call(["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True),
                call(["pactl", "unload-module", "456"], check=True),
            ]
        )

    def test_execute_command_success(self, radio_station, mock_subprocess):
        """Test successful command execution"""
        mock_subprocess["run"].return_value.stdout = "test output"

        radio_station.execute_command(["test", "command"])

        mock_subprocess["run"].assert_called_once_with(["test", "command"], capture_output=True, text=True, check=True)

    def test_execute_command_failure(self, radio_station, mock_subprocess):
        """Test command execution failure"""
        error = Exception("Command failed")
        mock_subprocess["run"].side_effect = error

        radio_station.execute_command(["test", "command"])
        # Should not raise exception, just print error message

    @patch("time.sleep")
    def test_start_browser_element_not_found(self, mock_sleep, radio_station, mock_webdriver):
        """Test browser start when element is not found"""
        from selenium.common.exceptions import TimeoutException

        # Setup WebDriverWait mock
        with patch("radiostations.base.WebDriverWait") as mock_wait:
            # Setup the wait mock to raise TimeoutException
            mock_wait_instance = Mock()
            mock_wait.return_value = mock_wait_instance
            mock_wait_instance.until.side_effect = TimeoutException()

            # Run the test and verify the exception message
            with pytest.raises(TimeoutException):
                radio_station.start_browser()

            # Verify browser was launched
            mock_webdriver["driver"].get.assert_called_with(radio_station.url)
            mock_wait.assert_called_once_with(mock_webdriver["driver"], 10)

    @patch("time.sleep")
    def test_start_browser_click_fails(self, mock_sleep, radio_station, mock_webdriver):
        """Test browser start when click fails"""
        # Setup WebDriverWait mock
        with patch("radiostations.base.WebDriverWait") as mock_wait:
            # Setup the wait mock to return an element that fails on click
            mock_wait_instance = Mock()
            mock_wait.return_value = mock_wait_instance
            mock_element = Mock()
            mock_element.click.side_effect = Exception("Click failed")
            mock_wait_instance.until.return_value = mock_element
            mock_webdriver["driver"].find_element.return_value = mock_element

            # Run the test and verify the exception message
            with pytest.raises(Exception, match="Click failed"):
                radio_station.start_browser()

            # Verify browser was launched and click was attempted
            mock_webdriver["driver"].get.assert_called_with(radio_station.url)
            mock_element.click.assert_called_once()
