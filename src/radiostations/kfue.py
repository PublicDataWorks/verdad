from radiostations.base import RadioStation


class Kfue(RadioStation):

    code = "KFUE-FM 106.7 MHz"
    state = "Arizona"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/fuego-1067-10386/",
            "virtual_speaker_kfue",
            "virtual_mic_kfue",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
