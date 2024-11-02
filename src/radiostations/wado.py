from radiostations.base import RadioStation


class Wado(RadioStation):

    code = "WADO-AM 1280 kHz"
    state = "New York"
    name = "La Campeona de Nueva York"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/wado-1280-am-5172/",
            "virtual_speaker_wado",
            "virtual_mic_wado",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
