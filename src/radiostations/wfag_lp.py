from radiostations.base import RadioStation


class WfagLp(RadioStation):

    code = "WFAG-LPFM 103.7 MHz"
    state = "Georgia"

    def __init__(self):
        super().__init__(
            "https://tunein.com/radio/SUPRA-1037-FM-s327412/",
            "virtual_speaker_wfag_lp",
            "virtual_mic_wfag_lp",
            "[class*='playButton-module__playButtonWrapper']",
            "video",
        )
