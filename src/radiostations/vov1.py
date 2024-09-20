from radiostations.base import RadioStation
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By


class Vov1(RadioStation):

    code = "VOV1"
    state = "Vietnam"

    def __init__(self):

        super().__init__(
            "https://worldradiomap.com/vn/play/vov1", f"virtual_speaker_{Vov1.code}", f"virtual_mic_{Vov1.code}"
        )

    def start_playing(self):
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "video")))
        print(f"Video element found on {self.url}")
        time.sleep(2)

        video_element = self.driver.find_element(By.ID, "video")
        self.driver.execute_script("arguments[0].play();", video_element)
        print("Click on the Play button")

        # Wait for a moment to let the audio start
        print("Wait a bit...")
        time.sleep(10)

        # Detailed audio checks
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
