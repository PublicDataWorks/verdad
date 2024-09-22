from radiostations.base import RadioStation


class Wumr(RadioStation):

    code = "WUMR-FM 106.1 MHz"
    state = "Pennsylvania"

    def __init__(self):
        super().__init__(
            "https://rumba1061.iheart.com/",
            "virtual_speaker_wumr",
            "virtual_mic_wumr",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
