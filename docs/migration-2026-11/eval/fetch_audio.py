"""Download the 18 eval recordings from the public R2 bucket (https://audio.verdad.app) into eval/audio/.

    python docs/migration-2026-11/eval/fetch_audio.py

About 250 MB (14.4 MB per half-hour mp3). Files already present are skipped. audio/ is git-ignored: the recordings
stay in R2 and are not committed. The manifest (data/manifest.json) maps each audio_files id to its R2 path.
"""

import json
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

for rec in json.load(open(HERE / "data" / "manifest.json")):
    dst = HERE / rec["local_audio"]
    dst.parent.mkdir(exist_ok=True)
    if not dst.exists():
        req = urllib.request.Request("https://audio.verdad.app/" + rec["file_path"], headers={"User-Agent": "verdad-eval"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            dst.write_bytes(resp.read())
    print(f"{dst.stat().st_size / 1e6:5.1f} MB  {rec['language']:<8} {rec['station_code']:<18} {dst.name}")
