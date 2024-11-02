from radiostations.base import RadioStation


class Wkaq(RadioStation):

    code = "WKAQ-AM 580 kHz"
    state = "Puerto Rico"
    name = "Analisis y Noticias"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/wkaq-580-5176/",
            "virtual_speaker_wkaq",
            "virtual_mic_wkaq",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
