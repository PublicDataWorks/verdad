from radiostations.base import RadioStation


class Kisf(RadioStation):

    code = "KISF-FM 103.5 MHz"
    state = "Nevada"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/zona-mx-1035-fm-5209/",
            "virtual_speaker_kisf",
            "virtual_mic_kisf",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
