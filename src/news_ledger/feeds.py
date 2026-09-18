"""Load and validate the news ledger feed list from ``config/news_feeds.yaml``.

Same shape as ``src/stations.py``: the YAML file is the source of truth, this module is the only
place that knows how it is stored, and validation happens on load rather than at use time.
"""

import os
from collections import Counter
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

# Repo root. Works in a checkout (src/news_ledger/feeds.py -> repo root) and inside the image,
# where the Dockerfile copies config/ next to src/.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "news_feeds.yaml"

Language = Literal["es", "en", "ar"]


class Feed(BaseModel):
    """One entry of ``config/news_feeds.yaml``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    language: Language
    tier: int = Field(ge=1, le=2)
    enabled: bool = True


def config_path(path=None) -> Path:
    """Resolve which config file to load: explicit argument, then $NEWS_FEEDS_CONFIG, then default."""
    if path is not None:
        return Path(path)
    override = os.getenv("NEWS_FEEDS_CONFIG")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


def load_feeds(path=None) -> list[Feed]:
    """Parse and validate the feed config, returning feeds in file order."""
    resolved = config_path(path)
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise FileNotFoundError(f"News feed config not found: {resolved}") from e

    if not isinstance(raw, dict) or "feeds" not in raw:
        raise ValueError(f"{resolved}: expected a mapping with a top-level 'feeds' key")

    entries = raw["feeds"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{resolved}: 'feeds' must be a non-empty list")

    feeds = [Feed(**entry) for entry in entries]
    _reject_duplicates([f.name for f in feeds], "feed name", resolved)
    _reject_duplicates([f.url for f in feeds], "feed url", resolved)
    return feeds


def enabled_feeds(path=None) -> list[Feed]:
    """The feeds the poller should fetch, in file order."""
    return [feed for feed in load_feeds(path) if feed.enabled]


def _reject_duplicates(values: list, label: str, resolved: Path) -> None:
    duplicates = sorted(value for value, count in Counter(values).items() if count > 1)
    if duplicates:
        raise ValueError(f"{resolved}: duplicate {label}(s): {', '.join(map(str, duplicates))}")
