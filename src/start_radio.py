import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

def is_audio_playing(driver):
    initial_time = driver.execute_script('return document.querySelector("#video").currentTime')
    time.sleep(2)
    current_time = driver.execute_script('return document.querySelector("#video").currentTime')
    return current_time > initial_time

def main():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--autoplay-policy=no-user-gesture-required")

    # Connect to the Selenium Standalone server
    driver = webdriver.Remote(
        command_executor='http://localhost:4444/wd/hub',
        options=chrome_options
    )
    print("WebDriver initialized successfully.")

    try:
        print("Navigating to the website...")
        driver.get("https://worldradiomap.com/vn/play/vov1")

        print("Waiting for the audio element to be present...")
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "video"))
        )

        print("Attempting to play audio...")
        driver.execute_script('document.querySelector("#video").play()')

        time.sleep(5)
        # Check if audio is playing
        if is_audio_playing(driver):
            print("Audio is playing (currentTime is increasing)")
        else:
            print("Audio is not playing (currentTime is not increasing)")

        print("Keeping the browser open for continuous playback. Press Ctrl+C to stop.")
        while True:
            time.sleep(5)
            if is_audio_playing(driver):
                print("Audio is playing")
            else:
                print("Audio is not playing")

    except KeyboardInterrupt:
        print("\nPlayback stopped by user.")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("Closing the browser...")
        driver.quit()

if __name__ == "__main__":
    main()
