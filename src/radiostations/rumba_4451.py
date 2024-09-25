from radiostations.base import RadioStation


class Rumba4451(RadioStation):

    code = "RUMBA 4451"
    state = "Arizona"

    def __init__(self):
        super().__init__(
            "https://www.iheart.com/live/rumba-4451/",
            "virtual_speaker_rumba_4451",
            "virtual_mic_rumba_4451",
            "button[aria-label='Play Button']",
            "video.jw-video",
        )
