from radiostations.base import RadioStation


class Khot(RadioStation):

    code = "KHOT-FM 105.9 MHz"
    state = "Arizona"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/que-buena-1059-fm-5207/",
            "virtual_speaker_khot",
            "virtual_mic_khot",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
