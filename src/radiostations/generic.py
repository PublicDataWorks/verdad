from radiostations.base import RadioStation


class GenericStation(RadioStation):
    """A browser-driven station built from a ``config/stations.yaml`` row.

    Replaces the former one-class-per-station modules; the six generic stations differ only in
    data (url, PulseAudio sink/source, selectors), all of which lives in the config file.

    ``code``, ``state`` and ``name`` used to be class attributes on the subclasses. They are
    instance attributes here, which reads the same everywhere they are used
    (``station.code`` etc. in src/generic_recording.py).
    """

    def __init__(self, station):
        # Note the two meanings of "driver": station.driver is the config block below, while
        # self.driver (set by RadioStation) is the Selenium webdriver handle.
        driver = station.driver
        if driver is None:
            raise ValueError(f"Station {station.code!r} has no driver settings; it is not a generic station")

        super().__init__(
            station.url,
            driver.sink,
            driver.source,
            driver.play_button_selector,
            driver.video_element_selector,
        )

        self.code = station.code
        self.state = station.state
        self.name = station.name

    def __repr__(self):
        return f"GenericStation(code={self.code!r})"
