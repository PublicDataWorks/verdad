# Radio Recording System

VERDAD supports two recording modes for capturing radio broadcasts:

## 1. Generic Recording System (Recommended)

The generic recording system uses Selenium with ChromeDriver to capture audio from web-based radio streams via browser automation.

### Architecture

- **Browser Automation:** Selenium with ChromeDriver in headless mode
- **Virtual Audio:** PulseAudio for capturing browser audio
- **Storage:** Cloudflare R2 (S3-compatible) for audio files
- **Metadata:** Supabase PostgreSQL for recording information

### Supported Radio Stations

Radio stations are implemented as adapter classes inheriting from `RadioStation` base class:

- **Khot** (KHOT - 105.9 FM, Arizona)
- **Kisf** (KISF - 99.9 FM, Arizona)
- **Krgt** (KRGT - 98.3 FM, Texas)
- **Wado** (WADO - 1280 AM, New York)
- **Waqi** (WAQI - 1600 AM, California)
- **Wkaq** (WKAQ - 580 AM, Puerto Rico)

### How It Works

1. **PulseAudio Setup:** Creates a virtual sink and source for capturing audio from the browser
2. **Browser Launch:** Starts a headless Chrome instance
3. **Navigation:** Loads the radio station webpage
4. **Play Button Detection:** Waits for and clicks the play button using CSS selectors
5. **Audio Capture:** Records audio from the virtual source using FFmpeg
6. **Upload:** Stores the MP3 file to R2 and metadata to Supabase

### Adding a New Radio Station

Create a new file in `src/radiostations/` (e.g., `mynewstation.py`):

```python
from radiostations.base import RadioStation

class MyNewStation(RadioStation):
    code = "STATION_CALL_LETTERS"
    state = "State Name"
    name = "Station Display Name"

    def __init__(self):
        super().__init__(
            url="https://example.com/stream",
            sink_name="virtual_speaker_mynewstation",
            source_name="virtual_mic_mynewstation",
            play_button_selector="button.play-button",  # CSS selector for play button
            video_element_selector="video#player",      # CSS selector for video/audio element
        )
```

Then import it in `src/generic_recording.py` and add to the station list.

### Environment Variables

```bash
# R2 Storage (Cloudflare)
R2_ENDPOINT_URL=https://your-account.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=your_bucket

# Supabase
SUPABASE_URL=your_project_url
SUPABASE_KEY=your_service_role_key

# Chrome/Chromium
CHROME_PATH=/path/to/chrome  # Optional, auto-detected by default
```

### Running Generic Recording

```bash
export FLY_PROCESS_GROUP=generic_recording
python src/generic_recording.py
```

## 2. Direct URL Recording

For non-web radio streams (direct HTTP/RTSP URLs), use the standard recording system:

```bash
python src/recording.py
```

This uses FFmpeg directly to capture audio from a URL without browser automation.

### Configuration

Stations are configured in the database via Supabase API. Each station requires:
- URL (HTTP/RTSP stream link)
- Name and call letters
- State/location
- Duration and bitrate settings

## Key Components

### RadioStation Base Class

Located in `src/radiostations/base.py`, provides:
- Virtual audio setup/teardown via PulseAudio
- Browser management with Selenium
- Audio capture coordination
- Metadata collection

### PulseAudio Integration

The system creates temporary virtual audio devices:
- **Null Sink:** Captures browser output
- **Virtual Source:** Provides audio to FFmpeg

Automatically handles cleanup on shutdown.

### Error Handling

- Automatic retry with exponential backoff
- Browser crash recovery
- Audio stream validation
- Sentry integration for monitoring
