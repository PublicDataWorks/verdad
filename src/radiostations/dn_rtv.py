from radiostations.base import RadioStation
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By


class DnRtv(RadioStation):

    code = "DN_RTV"
    state = "Vietnam"

    def __init__(self):
        super().__init__(
            "http://e.mytuner-radio.com/embed/dai-ptth-dong-nai-416874",
            f"virtual_speaker_{DnRtv.code}",
            f"virtual_mic_{DnRtv.code}",
        )

    def start_playing(self):
        WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, "play-button")))
        print(f"Play button found on {self.url}")

        play_button = self.driver.find_element(By.ID, "play-button")
        self.driver.execute_script("arguments[0].click();", play_button)
        print("Click on the Play button")

        # Wait for a moment to let the audio start
        print("Wait a bit...")
        time.sleep(10)

        video_element = self.driver.find_element(By.ID, "mtPlayer-video-element")

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
