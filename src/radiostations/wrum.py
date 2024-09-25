from radiostations.base import RadioStation


class Wrum(RadioStation):

    code = "WRUM-FM 100.3 MHz"
    state = "Florida, Orlando"

    def __init__(self):
        super().__init__(
            "https://rumba100.iheart.com/",
            "virtual_speaker_wrum",
            "virtual_mic_wrum",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
