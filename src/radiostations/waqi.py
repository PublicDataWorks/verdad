from radiostations.base import RadioStation


class Waqi(RadioStation):

    code = "WAQI - 710 AM"
    state = "Florida"
    name = "Radio Mambi"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/radio-mambi-710-am-5175/",
            "virtual_speaker_waqi",
            "virtual_mic_waqi",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
