"""Append-only JSONL cache of every decision call, errors included.

One file per (provider, model, variant): ``<root>/<provider>/<model>/<variant>.jsonl``, one record per
call. A record's key hashes (provider, model, variant, snippet_id, request body), so a changed state or
question wording is a new key while an identical request is served from the cache. When a key appears
more than once (an error later retried), the last record wins. ``report`` reads only this cache.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def cache_key(provider: str, model: str, variant: str, snippet_id: str, request_hash: str) -> str:
    return hashlib.sha256(json.dumps([provider, model, variant, snippet_id, request_hash]).encode()).hexdigest()


def _safe(part: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in part)


class ResponseCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, provider: str, model: str, variant: str) -> Path:
        return self.root / _safe(provider) / _safe(model) / f"{_safe(variant)}.jsonl"

    @staticmethod
    def _read(path: Path) -> list[dict]:
        records = []
        if not path.exists():
            return records
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue  # a line cut short by an interrupted run
        return records

    def load(self, provider: str, model: str, variant: str) -> dict[str, dict]:
        latest: dict[str, dict] = {}
        for record in self._read(self.path_for(provider, model, variant)):
            if record.get("key"):
                latest[record["key"]] = record
        return latest

    def append(self, record: dict) -> None:
        path = self.path_for(record["provider"], record["model"], record["variant"])
        path.parent.mkdir(parents=True, exist_ok=True)
        record.setdefault("created_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def all_records(self) -> list[dict]:
        """Every record under the root, last record per key."""
        latest: dict[str, dict] = {}
        if not self.root.exists():
            return []
        for path in sorted(self.root.glob("*/*/*.jsonl")):
            for record in self._read(path):
                if record.get("key"):
                    latest[record["key"]] = record
        return list(latest.values())
