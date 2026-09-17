"""GenericStation is built from a config/stations.yaml row.

These assertions used to live on six one-class-per-station modules. They now check that the
same six stations come out of the config with the same url, PulseAudio sink/source and
selectors, so the browser recorder behaves exactly as before.
"""

import pytest
from radiostations import GenericStation
from stations import stations_for

# What the six former subclasses (Khot, Kisf, Krgt, Wado, Waqi, Wkaq) declared.
EXPECTED = {
    "KHOT - 105.9 FM": {
        "state": "Arizona",
        "name": "Que Buena",
        "url": "https://www.iheart.com/live/que-buena-1059-fm-5207/",
        "sink_name": "virtual_speaker_khot",
        "source_name": "virtual_mic_khot",
    },
    "KISF - 103.5 FM": {
        "state": "Nevada",
        "name": "ZonaMX",
        "url": "https://www.iheart.com/live/zona-mx-1035-fm-5209/",
        "sink_name": "virtual_speaker_kisf",
        "source_name": "virtual_mic_kisf",
    },
    "KRGT - 99.3 FM": {
        "state": "Nevada",
        "name": "Rumba Hits caliente",
        "url": "https://www.iheart.com/live/latino-mix-993-fm-5221/",
        "sink_name": "virtual_speaker_krgt",
        "source_name": "virtual_mic_krgt",
    },
    "WKAQ - 580 AM": {
        "state": "Puerto Rico",
        "name": "Analisis y Noticias",
        "url": "https://www.iheart.com/live/wkaq-580-5176/",
        "sink_name": "virtual_speaker_wkaq",
        "source_name": "virtual_mic_wkaq",
    },
    "WADO - 1280 AM": {
        "state": "New York",
        "name": "La Campeona de Nueva York",
        "url": "https://www.iheart.com/live/wado-1280-am-5172/",
        "sink_name": "virtual_speaker_wado",
        "source_name": "virtual_mic_wado",
    },
    "WAQI - 710 AM": {
        "state": "Florida",
        "name": "Radio Mambi",
        "url": "https://www.iheart.com/live/radio-mambi-710-am-5175/",
        "sink_name": "virtual_speaker_waqi",
        "source_name": "virtual_mic_waqi",
    },
}

PLAY_BUTTON_SELECTOR = "button[aria-label='Play Button']"
VIDEO_ELEMENT_SELECTOR = "video.jw-video"


def generic_stations():
    return [GenericStation(row) for row in stations_for("generic")]


def test_generic_stations_match_the_former_subclasses():
    stations = generic_stations()
    assert [s.code for s in stations] == list(EXPECTED)

    for station in stations:
        expected = EXPECTED[station.code]
        assert station.state == expected["state"]
        assert station.name == expected["name"]
        assert station.url == expected["url"]
        assert station.sink_name == expected["sink_name"]
        assert station.source_name == expected["source_name"]
        assert station.play_button_selector == PLAY_BUTTON_SELECTOR
        assert station.video_element_selector == VIDEO_ELEMENT_SELECTOR


def test_all_stations_have_unique_codes():
    codes = [station.code for station in generic_stations()]
    assert len(codes) == len(set(codes)), "Duplicate station codes found"


def test_all_stations_have_unique_sink_names():
    sink_names = [station.sink_name for station in generic_stations()]
    assert len(sink_names) == len(set(sink_names)), "Duplicate sink names found"


def test_all_stations_have_unique_source_names():
    source_names = [station.source_name for station in generic_stations()]
    assert len(source_names) == len(set(source_names)), "Duplicate source names found"


def test_all_stations_have_valid_urls():
    for station in generic_stations():
        assert station.url.startswith("https://www.iheart.com/live/")
        assert station.url.endswith("/")


def test_all_stations_have_same_selectors():
    for station in generic_stations():
        assert station.play_button_selector == PLAY_BUTTON_SELECTOR
        assert station.video_element_selector == VIDEO_ELEMENT_SELECTOR


def test_generic_station_repr_names_the_code():
    station = generic_stations()[0]
    assert repr(station) == f"GenericStation(code={station.code!r})"


def test_generic_station_rejects_a_row_without_driver_settings():
    row = stations_for("max")[0]
    with pytest.raises(ValueError, match="has no driver settings"):
        GenericStation(row)
