import re
import subprocess
import time
from prefect import task
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager


class RadioStation:

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, url, sink_name, source_name, play_button_selector, video_element_selector):
        self.url = url
        self.sink_name = sink_name
        self.source_name = source_name
        self.driver = None
        self.sink_module = None
        self.source_module = None

        self.play_button_selector = play_button_selector
        self.video_element_selector = video_element_selector

    @task(log_prints=True)
    def setup_virtual_audio(self):
        self.ensure_pulseaudio_running()

        try:
            sink_result = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-null-sink",
                    f"sink_name={self.sink_name}",
                    f"sink_properties=device.description={self.sink_name}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.sink_module = sink_result.stdout.strip()

            source_result = subprocess.run(
                [
                    "pactl",
                    "load-module",
                    "module-virtual-source",
                    f"source_name={self.source_name}",
                    f"master={self.sink_name}.monitor",
                    f"source_properties=device.description={self.source_name}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.source_module = source_result.stdout.strip()

            # Set the sink to running state
            subprocess.run(["pactl", "suspend-sink", self.sink_name, "0"], check=True)

            # Set the source to running state
            subprocess.run(["pactl", "suspend-source", self.source_name, "0"], check=True)

            print(f"Virtual audio setup completed for {self.url}")

        except subprocess.CalledProcessError as e:
            print(f"Error setting up virtual audio: {e}")
            raise e

    @task(log_prints=True)
    def start_browser(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--use-pulse-audio")
        chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 17_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1"
        )

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=chrome_options)

        print(f"Launching url {self.url}")
        self.driver.get(self.url)

        self.start_playing()

        print("PulseAudio sinks:")
        self.execute_command(["pactl", "list", "short", "sinks"])
        print("PulseAudio sources:")
        self.execute_command(["pactl", "list", "short", "sources"])
        print("PulseAudio sink inputs:")
        self.execute_command(["pactl", "list", "sink-inputs"])

    def start_playing(self):
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, self.play_button_selector))
        )
        print(f"Play button found on {self.url}")
        time.sleep(5)

        print("Click on the Play button")
        play_button = self.driver.find_element(By.CSS_SELECTOR, self.play_button_selector)
        play_button.click()

        # Wait for a moment to let the audio start
        print("Wait a bit...")
        time.sleep(15)

        # Detailed audio checks
        try:
            video_element = self.driver.find_element(By.CSS_SELECTOR, self.video_element_selector)
        except Exception:
            print("Video element was not found. Skipped audio checks.")
            return

        is_playing = self.driver.execute_script(
            "return !arguments[0].paused && !arguments[0].ended && arguments[0].currentTime > 0;", video_element
        )
        current_time = self.driver.execute_script("return arguments[0].currentTime;", video_element)
        duration = self.driver.execute_script("return arguments[0].duration;", video_element)
        is_muted = self.driver.execute_script("return arguments[0].muted;", video_element)
        volume = self.driver.execute_script("return arguments[0].volume;", video_element)

        print(
            f"Is audio playing: {is_playing}. Current time: {current_time}. Duration: {duration}. Volume: {volume}. Muted: {is_muted}"
        )

        if not is_playing:
            raise Exception(f"Failed to start audio for {self.url}")

    def execute_command(self, command):
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            print(result.stdout)
        except Exception as e:
            print(f"An error occurred while executing command: {command}")
            print(str(e))

    def is_audio_playing(self):
        try:
            result = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, check=True)

            # Use a regex pattern that looks for State before Name
            pattern = rf"State: (\w+).*?Name: {re.escape(self.sink_name)}"
            sink_match = re.search(pattern, result.stdout, re.DOTALL)

            if sink_match:
                state = sink_match.group(1)
                is_playing = state == "RUNNING"
                return is_playing
            else:
                print(f"Sink {self.sink_name} not found in pactl output")
                print("PulseAudio sinks:")
                print(result.stdout)

            return False
        except subprocess.CalledProcessError as e:
            print(f"Error checking audio status: {e}")
            return False

    @task(log_prints=True)
    def stop(self):
        if self.driver:
            self.driver.quit()

        if self.sink_module:
            try:
                # Check if the sink module exists before unloading
                result = subprocess.run(
                    ["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True
                )
                if self.sink_module in result.stdout:
                    subprocess.run(["pactl", "unload-module", self.sink_module], check=True)
                    print(f"Unloaded sink module {self.sink_module}")
                else:
                    print(f"Sink module {self.sink_module} not found, possibly already unloaded")

            except subprocess.CalledProcessError as e:
                print(f"Error checking or unloading sink module {self.sink_module}: {e}")

        if self.source_module:
            try:
                # Check if the source module exists before unloading
                result = subprocess.run(
                    ["pactl", "list", "short", "modules"], capture_output=True, text=True, check=True
                )
                if self.source_module in result.stdout:
                    subprocess.run(["pactl", "unload-module", self.source_module], check=True)
                    print(f"Unloaded source module {self.source_module}")
                else:
                    print(f"Source module {self.source_module} not found, possibly already unloaded")
            except subprocess.CalledProcessError as e:
                print(f"Error checking or unloading source module {self.source_module}: {e}")

    def ensure_pulseaudio_running(self):
        try:
            subprocess.run(["pulseaudio", "--check"], check=True)
            print("PulseAudio is already running.")
            return
        except subprocess.CalledProcessError:
            print("PulseAudio is not running. Starting PulseAudio...")
            subprocess.Popen(
                ["pulseaudio", "--start", "--log-target=stderr", "--exit-idle-time=-1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(2)

        try:
            subprocess.run(["pulseaudio", "--check"], check=True)
            print("PulseAudio is now running.")
            return
        except subprocess.CalledProcessError:
            raise Exception("Failed to start PulseAudio.")
