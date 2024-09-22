from radiostations.base import RadioStation


class Kmma(RadioStation):

    code = "KMMA-FM 97.1 MHz"
    state = "Arizona"

    def __init__(self):
        super().__init__(
            "https://megatucson.iheart.com/",
            "virtual_speaker_kmma",
            "virtual_mic_kmma",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
