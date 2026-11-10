"""Load the pre-check evaluation dataset (JSONL) and enforce the leakage rule.

Leakage rule: only ``input`` plus the station name, station state and recording time from ``meta`` may
reach a model. ``label`` (the answer key) and ``meta.stage3_language`` (a Stage 3 output) never do.
:func:`model_input` is the single function that builds what a model may see; state builders take its
result, never a :class:`Clip`.
"""

import json
from dataclasses import dataclass, field

SPLITS = ("dev", "test")
# The only meta fields a model may see.
ALLOWED_META = ("station_name", "location_state", "recorded_at")


@dataclass
class Clip:
    snippet_id: str
    split: str
    weight: float
    label: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    input: dict = field(default_factory=dict)
    stratum: str = ""

    def score(self, field_name: str = "stage3_overall") -> float | None:
        value = self.label.get(field_name)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def parse_clip(obj: dict) -> Clip:
    if not isinstance(obj, dict):
        raise ValueError("line is not a JSON object")
    snippet_id = obj.get("snippet_id")
    if not snippet_id:
        raise ValueError("missing snippet_id")
    split = obj.get("split")
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
    weight = obj.get("weight", 1.0)
    try:
        weight = float(1.0 if weight is None else weight)
    except (TypeError, ValueError):
        raise ValueError(f"weight is not a number: {weight!r}") from None
    if weight <= 0:
        raise ValueError(f"weight must be > 0, got {weight}")
    return Clip(
        snippet_id=str(snippet_id),
        split=split,
        weight=weight,
        label=obj.get("label") or {},
        meta=obj.get("meta") or {},
        input=obj.get("input") or {},
        stratum=str(obj.get("stratum") or ""),
    )


def load_dataset(path: str) -> tuple[list[Clip], list[str]]:
    """Return (clips, problems). Malformed lines and duplicate ids are skipped and described in problems."""
    clips: list[Clip] = []
    problems: list[str] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                clip = parse_clip(json.loads(line))
            except ValueError as exc:  # json.JSONDecodeError is a ValueError
                problems.append(f"line {number}: {exc}")
                continue
            if clip.snippet_id in seen:
                problems.append(f"line {number}: duplicate snippet_id {clip.snippet_id}")
                continue
            seen.add(clip.snippet_id)
            clips.append(clip)
    return clips, problems


def model_input(clip: Clip) -> dict:
    """Everything a model may see about a clip, and nothing else."""
    allowed = {key: clip.meta.get(key) for key in ALLOWED_META}
    return {"input": dict(clip.input), "meta": allowed}


def select_clips(
    clips: list[Clip], split: str = "all", ids: list[str] | None = None, limit: int | None = None
) -> list[Clip]:
    chosen = [c for c in clips if split == "all" or c.split == split]
    if ids is not None:
        wanted = set(ids)
        chosen = [c for c in chosen if c.snippet_id in wanted]
    if limit is not None:
        chosen = chosen[:limit]
    return chosen


def read_ids_file(path: str) -> list[str]:
    """A JSON list of ids, or one id per line (blank lines and # comments ignored)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    stripped = text.strip()
    if stripped.startswith("["):
        return [str(i) for i in json.loads(stripped)]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
