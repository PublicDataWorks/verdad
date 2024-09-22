from radiostations.base import RadioStation


class Wbzy(RadioStation):

    code = "WBZY-FM 105.7 MHz"
    state = "Georgia"

    def __init__(self):
        super().__init__(
            "https://z1057atlanta.iheart.com/",
            "virtual_speaker_wbzy",
            "virtual_mic_wbzy",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
