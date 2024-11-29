from radiostations.khot import Khot
from radiostations.kisf import Kisf
from radiostations.krgt import Krgt
from radiostations.wado import Wado
from radiostations.waqi import Waqi
from radiostations.wkaq import Wkaq

class TestKhot:
    def test_init(self):
        """Test Khot radio station initialization"""
        station = Khot()
        assert station.code == "KHOT - 105.9 FM"
        assert station.state == "Arizona"
        assert station.name == "Que Buena"
        assert station.url == "https://www.iheart.com/live/que-buena-1059-fm-5207/"
        assert station.sink_name == "virtual_speaker_khot"
        assert station.source_name == "virtual_mic_khot"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

class TestKisf:
    def test_init(self):
        """Test Kisf radio station initialization"""
        station = Kisf()
        assert station.code == "KISF - 103.5 FM"
        assert station.state == "Nevada"
        assert station.name == "ZonaMX"
        assert station.url == "https://www.iheart.com/live/zona-mx-1035-fm-5209/"
        assert station.sink_name == "virtual_speaker_kisf"
        assert station.source_name == "virtual_mic_kisf"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

class TestKrgt:
    def test_init(self):
        """Test Krgt radio station initialization"""
        station = Krgt()
        assert station.code == "KRGT - 99.3 FM"
        assert station.state == "Nevada"
        assert station.name == "Rumba Hits caliente"
        assert station.url == "https://www.iheart.com/live/latino-mix-993-fm-5221/"
        assert station.sink_name == "virtual_speaker_krgt"
        assert station.source_name == "virtual_mic_krgt"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

class TestWado:
    def test_init(self):
        """Test Wado radio station initialization"""
        station = Wado()
        assert station.code == "WADO - 1280 AM"
        assert station.state == "New York"
        assert station.name == "La Campeona de Nueva York"
        assert station.url == "https://www.iheart.com/live/wado-1280-am-5172/"
        assert station.sink_name == "virtual_speaker_wado"
        assert station.source_name == "virtual_mic_wado"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

class TestWaqi:
    def test_init(self):
        """Test Waqi radio station initialization"""
        station = Waqi()
        assert station.code == "WAQI - 710 AM"
        assert station.state == "Florida"
        assert station.name == "Radio Mambi"
        assert station.url == "https://www.iheart.com/live/radio-mambi-710-am-5175/"
        assert station.sink_name == "virtual_speaker_waqi"
        assert station.source_name == "virtual_mic_waqi"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

class TestWkaq:
    def test_init(self):
        """Test Wkaq radio station initialization"""
        station = Wkaq()
        assert station.code == "WKAQ - 580 AM"
        assert station.state == "Puerto Rico"
        assert station.name == "Analisis y Noticias"
        assert station.url == "https://www.iheart.com/live/wkaq-580-5176/"
        assert station.sink_name == "virtual_speaker_wkaq"
        assert station.source_name == "virtual_mic_wkaq"
        assert station.play_button_selector == "button[aria-label='Play Button']"
        assert station.video_element_selector == "video.jw-video"

def test_all_stations_have_unique_codes():
    """Test that all station codes are unique"""
    stations = [Khot(), Kisf(), Krgt(), Wado(), Waqi(), Wkaq()]
    codes = [station.code for station in stations]
    assert len(codes) == len(set(codes)), "Duplicate station codes found"

def test_all_stations_have_unique_sink_names():
    """Test that all station sink names are unique"""
    stations = [Khot(), Kisf(), Krgt(), Wado(), Waqi(), Wkaq()]
    sink_names = [station.sink_name for station in stations]
    assert len(sink_names) == len(set(sink_names)), "Duplicate sink names found"

def test_all_stations_have_unique_source_names():
    """Test that all station source names are unique"""
    stations = [Khot(), Kisf(), Krgt(), Wado(), Waqi(), Wkaq()]
    source_names = [station.source_name for station in stations]
    assert len(source_names) == len(set(source_names)), "Duplicate source names found"

def test_all_stations_have_valid_urls():
    """Test that all station URLs are valid iheart.com URLs"""
    stations = [Khot(), Kisf(), Krgt(), Wado(), Waqi(), Wkaq()]
    for station in stations:
        assert station.url.startswith("https://www.iheart.com/live/")
        assert station.url.endswith("/")

def test_all_stations_have_same_selectors():
    """Test that all stations use the same selectors"""
    stations = [Khot(), Kisf(), Krgt(), Wado(), Waqi(), Wkaq()]
    expected_play_button_selector = "button[aria-label='Play Button']"
    expected_video_element_selector = "video.jw-video"

    for station in stations:
        assert station.play_button_selector == expected_play_button_selector
        assert station.video_element_selector == expected_video_element_selector
