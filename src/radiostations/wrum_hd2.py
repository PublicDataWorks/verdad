from radiostations.base import RadioStation


class WrumHd2(RadioStation):

    code = "WRUM-FM HD2 97.1 MHz"
    state = "Florida, Orlando"

    def __init__(self):
        super().__init__(
            "https://lamegaorlando.iheart.com/",
            "virtual_speaker_wrum_hd2",
            "virtual_mic_wrum_hd2",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
