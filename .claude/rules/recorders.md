---
paths:
  - "src/recording.py"
  - "src/generic_recording.py"
  - "src/radiostations/**"
  - "src/stations.py"
  - "config/stations.yaml"
  - "scripts/start_recording.sh"
---

# Recorders

## The station list lives in one file

`config/stations.yaml` is the only place station data exists. `src/stations.py` loads and validates it
(pydantic `Station`/`Driver`, unique `code`/`url`/sink/source/`process_group`) and is the only module that
knows the file format:

- `stations_for("max" | "lite" | "generic")` -> `Station` rows in file order, enabled ones by default.
- `station_dicts(recorders=("max", "lite"))` -> the legacy four-key dicts (`code`, `url`, `state`, `name`)
  that `src/recording.py` and the Supabase writes have always used. `utils.fetch_radio_stations()` is a
  thin wrapper over it.
- `station_by_process_group` / `station_by_code` -> lookups for the generic recorder.
- `python -m stations prefect-runs` -> one `"<flow name>/<code>"` line per enabled station, which is what
  `scripts/start_recording.sh` iterates over instead of hard-coded arrays (it calls `python3` and aborts
  rather than triggering a partial set of deployments if the read fails). `python -m stations codes
  --recorder lite` is the quick way to see what one machine will serve.

`load_stations()` resolves `config/stations.yaml` relative to the repo root and honours `$STATIONS_CONFIG`;
tests point it at a temporary file rather than mutating the real one.

## `recorder` is topology, not preference

Each station's `recorder` field assigns it to a machine; there is no positional split any more. `max` and
`lite` are the two `fly.recording_worker.toml` process groups (8 GB / 4 GB, one ffmpeg process per station),
`generic` is `fly.generic_recording_worker.toml` (one Chrome + PulseAudio machine per station). Changing the
field only takes effect on `fly deploy`, so treat it as part of the deploy topology. Adding a station is one
YAML entry plus its snapshot in `tests/test_stations.py`; see docs/OPERATIONS.md, "Adding or disabling a station".

`code` is the Prefect deployment name and `get_url_hash(url)` (last 6 hex of sha256) is the R2 prefix
`radio_<hash>/`, so renaming a code orphans a deployment and editing a url moves that station's audio.
`tests/test_stations.py` snapshots the per-recorder code lists, the 59 Prefect run strings and a few url
hashes for exactly that reason - a diff there means a real production change, not a test to relax.

## ffmpeg recorders vs Selenium recorders

`src/recording.py` records plain HTTP/HLS streams with ffmpeg. `src/generic_recording.py` covers the six
web-only stations that need a real browser. There is one class, `GenericStation` in
`src/radiostations/generic.py`, built from a `Station` row; `RadioStation` in `src/radiostations/base.py`
owns the Chrome/Selenium lifecycle (`start_browser`, `start_playing`, `is_audio_playing`, `stop`) and the
PulseAudio virtual sink plumbing (`setup_virtual_audio`, `ensure_pulseaudio_running`). Per-station data
(url, sink/source, selectors) comes from the YAML `driver` block, so a new generic station needs no new
Python. Put shared browser behavior in `base.py`.

## `FLY_PROCESS_GROUP` dispatch

Both entrypoints read `FLY_PROCESS_GROUP` under `if __name__ == "__main__"`:

- `src/recording.py`: `max_recorder` -> `station_dicts(["max"])`, `lite_recorder` -> `station_dicts(["lite"])`,
  each served via `serve_deployments(...)` with one deployment per station.
- `src/generic_recording.py`: `station_by_process_group(...)` -> one station, one deployment. An unknown
  group still raises.

The valid values are the `[processes]` keys in the `fly.*.toml` files and the `process_group` fields in
`config/stations.yaml`; keep them in sync.

## Tests must not touch Chrome or the network

`radiostations/base.py` imports `Service` and `ChromeDriverManager` into its own namespace and calls
`Service(ChromeDriverManager().install())` in `start_browser`, so tests patch **the names as bound in
`base`** - `radiostations.base.Service`, `radiostations.base.ChromeDriverManager`,
`radiostations.base.WebDriverWait` (see the `mock_webdriver` fixture in `tests/radiostations/test_base.py`).
Patching `selenium.webdriver.chrome.service.Service` or `webdriver_manager.chrome.ChromeDriverManager`
instead leaves the bound names alone and the real `ChromeDriverManager` downloads chromedriver over the
network. `subprocess`/`psutil` calls and `time.sleep` need patching too; `tests/test_recording.py` and
`tests/test_generic_recording.py` patch the module-level `recording.s3_client` /
`generic_recording.supabase_client` singletons and `generic_recording.GenericStation`.
