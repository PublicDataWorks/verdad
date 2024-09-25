from radiostations.base import RadioStation


class Wztu(RadioStation):

    code = "WZTU-FM 94.9 MHz"
    state = "Florida"

    def __init__(self):
        super().__init__(
            "https://tu949fm.iheart.com/",
            "virtual_speaker_wztu",
            "virtual_mic_wztu",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
