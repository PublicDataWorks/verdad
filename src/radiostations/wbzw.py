from radiostations.base import RadioStation


class Wbzw(RadioStation):

    code = "WBZW-FM 96.7 MHz"
    state = "Georgia"

    def __init__(self):
        super().__init__(
            "https://elpatron967.iheart.com/",
            "virtual_speaker_wbzw",
            "virtual_mic_wbzw",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
