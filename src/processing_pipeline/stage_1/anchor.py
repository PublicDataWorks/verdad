"""Word-anchored snippet times (STAGE1_ANCHOR_TIMESTAMPS=true).

Main detection reads one ``[MM:SS]`` line per 20 s window, so its ``start_time``/``end_time`` are window starts, not
measurements. When the recording has Transcribe word timestamps, each flagged snippet's ``transcription`` is
matched back to the words and the snippet gets the times of the matched span instead.

A match is used only when it is good enough (``MIN_SCORE``) and lies within ``WINDOW_TOLERANCE_S`` of the model's own
window; otherwise the model's times stay. Matching is token-level ``difflib.SequenceMatcher`` on normalized words
(case-folded, punctuation and diacritics removed), so filler words the detection model dropped ("eh", "este") and
small wording differences lower the score a little instead of breaking the match.

Stored per snippet (``anchor_flagged_snippets``): ``start_time``/``end_time`` as whole-second ``MM:SS`` (start rounded
down, end rounded up; the format Stage 2 already parses), ``start_s``/``end_s`` (exact seconds, None when not
anchored), ``anchor_score``, ``anchor_status`` and the model's originals in ``llm_start_time``/``llm_end_time``.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

# Share of matched tokens, 2*M / (query tokens + span tokens), below which a match is not trusted.
MIN_SCORE = 0.6

# How far outside the model's window (in seconds, each side) the matched span may lie.
WINDOW_TOLERANCE_S = 60

_NON_WORD = re.compile(r"[\W_]+")


@dataclass(frozen=True)
class Anchor:
    start_s: float | None
    end_s: float | None
    score: float
    accepted: bool
    # matched | low_score | out_of_window | no_words | empty_transcription | unparseable_llm_times
    reason: str


def normalize(token: str) -> str:
    """Case-folded, without diacritics (Spanish accents, Arabic harakat) or punctuation."""
    decomposed = unicodedata.normalize("NFKD", token.casefold())
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD.sub("", without_marks)


def tokenize(text: str) -> list[str]:
    return [token for token in (normalize(part) for part in (text or "").split()) if token]


def parse_clock(value) -> float | None:
    """``"MM:SS"``, ``"HH:MM:SS"`` or ``"SS"`` -> seconds; None when it is not one of those."""
    if value is None:
        return None
    parts = str(value).strip().split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return seconds


def format_clock(seconds: int) -> str:
    """Whole seconds -> ``MM:SS`` (minutes are not wrapped into hours, like the detection prompt's examples)."""
    seconds = max(int(seconds), 0)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _best_span(query: list[str], tokens: list[str]) -> tuple[float, int, int] | None:
    """``(score, first token, last token)`` of the span of ``tokens`` that best matches ``query``.

    The matching blocks of one SequenceMatcher pass are monotone in both sequences; the span is the run of
    consecutive blocks that maximizes 2*M / (len(query) + span length), which drops stray common words matched far
    from the real passage.
    """
    blocks = [b for b in SequenceMatcher(None, query, tokens, autojunk=False).get_matching_blocks() if b.size]
    best = None
    for first in range(len(blocks)):
        matched = 0
        for last in range(first, len(blocks)):
            matched += blocks[last].size
            span_end = blocks[last].b + blocks[last].size - 1
            score = 2 * matched / (len(query) + span_end - blocks[first].b + 1)
            if best is None or score > best[0]:
                best = (score, blocks[first].b, span_end)
    return best


def _match(query: list[str], words: list[dict], indexes: list[int]) -> tuple[float, float, float] | None:
    """``(score, start_s, end_s)`` of the best span among ``words[i] for i in indexes``."""
    kept = [(i, token) for i in indexes if (token := normalize(words[i]["text"]))]
    if not kept:
        return None
    span = _best_span(query, [token for _, token in kept])
    if span is None:
        return None
    score, first, last = span
    first_word, last_word = words[kept[first][0]], words[kept[last][0]]
    return score, float(first_word["start"]), float(last_word.get("end", last_word["start"]))


def anchor_snippet(
    transcription: str,
    words: list[dict],
    llm_start_s: float,
    llm_end_s: float,
    min_score: float = MIN_SCORE,
    tolerance_s: float = WINDOW_TOLERANCE_S,
) -> Anchor:
    """Where in ``words`` the snippet ``transcription`` was said, if it can be found near the model's window."""
    query = tokenize(transcription)
    if not query:
        return Anchor(None, None, 0.0, False, "empty_transcription")
    if not words:
        return Anchor(None, None, 0.0, False, "no_words")

    low = min(llm_start_s, llm_end_s) - tolerance_s
    high = max(llm_start_s, llm_end_s) + tolerance_s

    def in_window(start: float, end: float) -> bool:
        return low <= start and end <= high

    # Search near the model's window first: a phrase repeated elsewhere in the hour (a slogan, an ad) cannot win.
    nearby = [i for i, w in enumerate(words) if in_window(w["start"], w.get("end", w["start"]))]
    match = _match(query, words, nearby)
    if match and match[0] >= min_score:
        score, start, end = match
        return Anchor(start, end, score, True, "matched")

    # Nothing good nearby: look at the whole recording only to say why the model's times are kept.
    anywhere = _match(query, words, list(range(len(words))))
    if anywhere and anywhere[0] >= min_score and not in_window(anywhere[1], anywhere[2]):
        return Anchor(anywhere[1], anywhere[2], anywhere[0], False, "out_of_window")
    return Anchor(None, None, match[0] if match else 0.0, False, "low_score")


def anchor_flagged_snippets(
    snippets: list[dict],
    words: list[dict],
    min_score: float = MIN_SCORE,
    tolerance_s: float = WINDOW_TOLERANCE_S,
) -> list[Anchor]:
    """Rewrite each snippet's times from ``words`` in place (see the module docstring); returns one Anchor each."""
    anchors = []
    for snippet in snippets:
        llm_start, llm_end = snippet.get("start_time"), snippet.get("end_time")
        start_s, end_s = parse_clock(llm_start), parse_clock(llm_end)
        if start_s is None or end_s is None:
            anchor = Anchor(None, None, 0.0, False, "unparseable_llm_times")
        else:
            anchor = anchor_snippet(snippet.get("transcription") or "", words, start_s, end_s, min_score, tolerance_s)

        snippet["llm_start_time"] = llm_start
        snippet["llm_end_time"] = llm_end
        snippet["anchor_score"] = round(anchor.score, 3)
        snippet["anchor_status"] = anchor.reason
        if anchor.accepted:
            snippet["start_time"] = format_clock(math.floor(anchor.start_s))
            snippet["end_time"] = format_clock(math.ceil(anchor.end_s))
            snippet["start_s"] = round(anchor.start_s, 3)
            snippet["end_s"] = round(anchor.end_s, 3)
        else:
            snippet["start_s"] = None
            snippet["end_s"] = None
        anchors.append(anchor)

    accepted = sum(a.accepted for a in anchors)
    print(f"Anchored {accepted}/{len(anchors)} flagged snippets to word timestamps")
    return anchors
