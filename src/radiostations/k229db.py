from radiostations.base import RadioStation


class K229db(RadioStation):

    code = "K229DB-FM 93.7 MHz"
    state = "Arizona"

    def __init__(self):
        super().__init__(
            "https://elpatronphoenix.iheart.com/",
            "virtual_speaker_k229db",
            "virtual_mic_k229db",
            "button[aria-label='Play Stream Now']",
            "video.jw-video",
        )
