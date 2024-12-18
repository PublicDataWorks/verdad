from radiostations.base import RadioStation


class Krgt(RadioStation):

    code = "KRGT - 99.3 FM"
    state = "Nevada"
    name = "Rumba Hits caliente"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/latino-mix-993-fm-5221/",
            "virtual_speaker_krgt",
            "virtual_mic_krgt",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
