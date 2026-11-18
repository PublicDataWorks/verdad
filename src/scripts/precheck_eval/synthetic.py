"""A seeded synthetic dataset in the real schema, for tests, dry runs and harness sanity checks.

High-score clips get the word ``contradicts`` more often in their Stage 1 explanation, which the
``fake-signal`` model counts; so ``fake-signal`` is correlated with the label only through the input,
the way a real model would be. Low-score clips are oversampled less, so their weight is higher.
"""

import json
import random
from datetime import datetime, timedelta, timezone

from .providers import FAKE_SIGNAL_WORD

STATIONS = [("KABC", "Radio Uno", "CA"), ("WXYZ", "La Voz", "FL"), ("KDEF", "Radio Sawa", "MI"),
            ("WGHI", "Radio Mexicana", "TX"), ("KJKL", "La Nueva", "AZ"), ("WMNO", "Radio Arabe", "NY")]
CATEGORIES = ["Election Integrity", "Health", "Immigration", "Conspiracy Theories", "Economy", "War"]
WORDS = "el la de que y en un ser se no haber por con su para como estar tener le lo todo pero más".split()
ARABIC = "في من على إلى أن هذا التي الذي مع كان عن ما لا هو".split()


def _score(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.68:
        return rng.choice([0, 0, 0, 5, 10, 20, 25, 30, 35])
    if r < 0.80:
        return rng.randint(40, 79)
    if r < 0.92:
        return rng.randint(80, 89)
    return rng.randint(90, 100)


def make_clip(i: int, rng: random.Random) -> dict:
    score = _score(rng)
    code, name, state = rng.choice(STATIONS)
    arabic = code in ("KDEF", "WMNO")
    signal = max(0, round(score / 25 + rng.gauss(0, 0.8)))
    explanation = "The speaker discusses a recent event. " + " ".join(
        f"The claim {FAKE_SIGNAL_WORD} public records." for _ in range(signal)
    )
    vocab = ARABIC if arabic else WORDS
    n_words = rng.choice([80, 200, 400, 900]) if rng.random() > 0.05 else 5000
    excerpt = " ".join(rng.choice(vocab) for _ in range(n_words))
    recorded = datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(hours=rng.randint(0, 24 * 60))
    stratum = "high" if score >= 80 else "mid" if score >= 40 else "low"
    quote = " ".join(rng.choice(vocab) for _ in range(30)) + " " + " ".join(
        FAKE_SIGNAL_WORD for _ in range(signal)
    )
    core = " ".join(rng.choice(vocab) for _ in range(rng.choice([0, 60, 150])))
    final = score if score < 90 or rng.random() > 0.1 else rng.choice([45, 85, 95])
    return {
        "snippet_id": f"synthetic-{i:05d}",
        "split": "dev" if i % 2 == 0 else "test",
        "stratum": stratum,
        "weight": {"high": 1.0, "mid": 2.0, "low": 3.0}[stratum],
        "label": {
            "stage3_overall": score,
            "final_overall": final,
            "stage4_changed_score": final != score,
            "analyzed_by": rng.choice(["gemini-3.5-flash", "gemini-3.8-flash"]),
            "status": "Processed",
            "analyzed_at": recorded.isoformat(),
        },
        "meta": {
            "station_code": code,
            "station_name": name,
            "location_state": state,
            "recorded_at": recorded.isoformat(),
            "stage3_language": "Arabic" if arabic else "Spanish",
            "live": rng.random() < 0.7,
        },
        "input": {
            "stage1_explanation": explanation,
            "stage1_keywords": rng.sample(vocab, k=rng.randint(0, 4)),
            "stage1_categories": rng.sample(CATEGORIES, k=rng.randint(1, 3)),
            "stage1_transcript_excerpt": excerpt,
            "start_time": "00:01:00",
            "end_time": "00:02:30",
            "duration_s": 90,
            "stage1_language": "Arabic" if arabic else "Spanish",
            "stage1_extra": {
                "flagged_transcription": quote,
                "core_excerpt": core,
                "n_flagged_in_recording": rng.randint(1, 5),
                "detection_prompt_version_id": rng.choice(["15fdb4a2-synthetic", "912a43df-synthetic"]),
            },
        },
    }


def make_dataset(n: int = 200, seed: int = 475) -> list[dict]:
    rng = random.Random(seed)
    return [make_clip(i, rng) for i in range(n)]


def write_dataset(path: str, n: int = 200, seed: int = 475) -> int:
    rows = make_dataset(n, seed)
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)
