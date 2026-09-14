---
paths:
  - "src/recording.py"
  - "src/generic_recording.py"
  - "src/radiostations/**"
  - "scripts/start_recording.sh"
---

# Recorders

## The station list is hard-coded in three places

`src/utils.py::fetch_radio_stations()` returns 53 dicts (`code`, `url`, `state`, ...). `src/recording.py`
splits that list **by position**: `radio_stations[:39]` is the max recorder, `radio_stations[39:]` the lite
recorder. `scripts/start_recording.sh` then names the resulting Prefect deployments as strings
(`"Audio Recording: Lite Recorder/<CODE>"`, same for Max Recorder).

Consequences: adding, removing or reordering a station shifts the 39 boundary and silently moves stations
between recorders. Any change touches `src/utils.py`, the two slices in `src/recording.py` and the arrays in
`scripts/start_recording.sh`, and the station-count assertions in `tests/test_utils.py`.

## ffmpeg recorders vs Selenium recorders

`src/recording.py` records plain HTTP streams with ffmpeg. `src/generic_recording.py` covers the six web-only
stations that need a real browser: `Khot`, `Kisf`, `Krgt`, `Wado`, `Waqi`, `Wkaq`, one class per file in
`src/radiostations/`, all subclassing `RadioStation` in `src/radiostations/base.py`. The base class owns the
Chrome/Selenium lifecycle (`start_browser`, `start_playing`, `is_audio_playing`, `stop`) and the PulseAudio
virtual sink plumbing (`setup_virtual_audio`, `ensure_pulseaudio_running`); a subclass supplies only URL,
sink/source names and the play-button and video-element selectors. Put shared browser behavior in `base.py`.

## `FLY_PROCESS_GROUP` dispatch

Both entrypoints read `FLY_PROCESS_GROUP` under `if __name__ == "__main__"` and `match` on it:

- `src/recording.py`: `max_recorder` -> `radio_stations[:39]`, `lite_recorder` -> `radio_stations[39:]`,
  each served via `serve_deployments(...)` with one deployment per station.
- `src/generic_recording.py`: `radio_khot`, `radio_kisf`, `radio_krgt`, `radio_wkaq`, `radio_wado`,
  `radio_waqi` -> one station instance, one deployment. Anything else raises.

The valid values are the `[processes]` keys in the `fly.*.toml` files; keep the three in sync.

## Tests must not touch Chrome or the network

`radiostations/base.py` imports `Service` and `ChromeDriverManager` into its own namespace and calls
`Service(ChromeDriverManager().install())` in `start_browser`, so tests patch **the names as bound in
`base`** - `radiostations.base.Service`, `radiostations.base.ChromeDriverManager`,
`radiostations.base.WebDriverWait` (see the `mock_webdriver` fixture in `tests/radiostations/test_base.py`).
Patching `selenium.webdriver.chrome.service.Service` or `webdriver_manager.chrome.ChromeDriverManager`
instead leaves the bound names alone and the real `ChromeDriverManager` downloads chromedriver over the
network. `subprocess`/`psutil` calls and `time.sleep` need patching too; `tests/test_recording.py` and
`tests/test_generic_recording.py` patch the module-level `recording.s3_client` /
`generic_recording.supabase_client` singletons and the station classes as bound in `generic_recording`.
