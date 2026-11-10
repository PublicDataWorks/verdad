"""State variants and question sets for the decision-model pre-check. Add new ones here.

A *state* is the text a decision model reads about one clip. A *question set* is the named, typed questions
asked about it in one call. Both are built only from :func:`dataset.model_input`, never from a ``Clip``,
so the answer key cannot leak into a request.

The ``stage3_band`` rubric mirrors the Stage 3 confidence bands in ``prompts/stage_3/analysis_prompt.md``
("Confidence Scoring and Verification Requirements"): 0 = accurate or opinion only, 1-39 = unsubstantiated
or exaggerated with no contradicting evidence, 40-79 = misleading or partly contradicted, 80-100 = specific
claims definitively contradicted by reputable sources. Level 2 and 3 split the 40-79 band in two.
"""

import hashlib
import json
import random
from dataclasses import dataclass

from .config import CHARS_PER_TOKEN, MAX_STATE_TOKENS, estimate_tokens

EXPLANATION_MAX_CHARS = 4_000
MIN_EXCERPT_CHARS = 500
HEAD_SHARE = 0.6


@dataclass
class State:
    text: str
    truncated: bool
    excerpt_chars: int  # original length of the long text parts (quote, core, excerpt)
    excerpt_kept_chars: int
    est_tokens: int
    truncated_parts: tuple[str, ...] = ()


def truncate_middle(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep the head and tail of ``text`` within ``max_chars``, marking the cut."""
    if len(text) <= max_chars:
        return text, False
    marker_budget = 40
    keep = max(0, max_chars - marker_budget)
    head = int(keep * HEAD_SHARE)
    tail = keep - head
    omitted = len(text) - head - tail
    tail_text = text[-tail:] if tail else ""
    return f"{text[:head]}\n[... {omitted} characters omitted ...]\n{tail_text}", True


def _join(values) -> str:
    if not values:
        return "(none)"
    if isinstance(values, (list, tuple)):
        return ", ".join(str(v) for v in values if v not in (None, "")) or "(none)"
    return str(values)


def _date(recorded_at) -> str:
    return str(recorded_at)[:10] if recorded_at else "unknown"


def _station(meta: dict) -> str:
    name = meta.get("station_name") or "unknown station"
    state = meta.get("location_state")
    return f"{name} ({state})" if state else str(name)


def _extra(inp: dict) -> dict:
    extra = inp.get("stage1_extra")
    return extra if isinstance(extra, dict) else {}


# Long text parts: name -> (header, getter). Truncated head + tail to fit the state budget.
TEXT_PARTS = {
    "quote": (
        "Quote of the flagged passage by an automated first pass (original language):",
        lambda inp: _extra(inp).get("flagged_transcription"),
    ),
    "core": (
        "Transcript of the flagged passage (original language):",
        lambda inp: _extra(inp).get("core_excerpt"),
    ),
    "excerpt": (
        "Transcript excerpt with surrounding context (original language):",
        lambda inp: inp.get("stage1_transcript_excerpt"),
    ),
}


def build_state(model_in: dict, variant: str, max_tokens: int = MAX_STATE_TOKENS) -> State:
    """Build the state text for ``variant`` from :func:`dataset.model_input` output.

    Short parts come first; the long text parts share what is left of the ``max_tokens`` budget in order,
    each cut head + tail when it does not fit (a part that needs less leaves the rest to the next one).
    """
    if variant not in STATE_VARIANTS:
        raise ValueError(f"unknown state variant {variant!r}; choose from {sorted(STATE_VARIANTS)}")
    inp = model_in.get("input") or {}
    meta = model_in.get("meta") or {}
    parts = STATE_VARIANTS[variant]
    lines: list[str] = []
    if "station" in parts:
        lines.append(f"Radio station: {_station(meta)}")
        lines.append(f"Recorded on: {_date(meta.get('recorded_at'))}")
    if "explanation" in parts:
        explanation, _ = truncate_middle(str(inp.get("stage1_explanation") or ""), EXPLANATION_MAX_CHARS)
        lines.append(f"Screening note from an automated first pass: {explanation or '(none)'}")
    if "flags" in parts:
        lines.append(f"Keywords noted by the first pass: {_join(inp.get('stage1_keywords'))}")
        lines.append(f"Topics noted by the first pass: {_join(inp.get('stage1_categories'))}")
    texts = [p for p in parts if p in TEXT_PARTS]
    remaining = int(max_tokens * CHARS_PER_TOKEN) - sum(len(line) + 1 for line in lines)
    original = kept = 0
    cut: list[str] = []
    for i, part in enumerate(texts):
        header, getter = TEXT_PARTS[part]
        text = str(getter(inp) or "")
        share = (remaining - len(header) - 2) // (len(texts) - i)
        kept_text, was_cut = truncate_middle(text, max(MIN_EXCERPT_CHARS, share))
        if was_cut:
            cut.append(part)
        original += len(text)
        kept += len(kept_text)
        remaining -= len(header) + len(kept_text) + 2
        lines.append(header)
        lines.append(kept_text or "(empty)")
    text = "\n".join(lines)
    return State(
        text=text,
        truncated=bool(cut),
        excerpt_chars=original,
        excerpt_kept_chars=kept,
        est_tokens=estimate_tokens(text),
        truncated_parts=tuple(cut),
    )


# Which parts each state variant carries.
STATE_VARIANTS: dict[str, tuple[str, ...]] = {
    # Stage 1 explanation + keywords + categories + station name/state + recorded date
    "flag": ("station", "explanation", "flags"),
    # transcript excerpt (90 s lead-in + flagged window + 60 s tail) + station + date, no Stage 1 output
    "excerpt": ("station", "excerpt"),
    # both
    "full": ("station", "explanation", "flags", "excerpt"),
    # Stage 1's own quote of the claim + explanation + keywords + categories (short)
    "quote": ("explanation", "flags", "quote"),
    # transcript of the flagged window only + explanation + keywords + categories (short)
    "core": ("explanation", "flags", "core"),
    # Parallel: the claim text only. No station name or date (VER-443: station metadata steered web retrieval).
    "claim": ("quote", "core"),
}

CONTENT_TYPES = {
    "news_report": "A news report or news bulletin.",
    "political_commentary": "Political commentary, analysis or opinion.",
    "health_medical": "Health, medical or nutrition advice or discussion.",
    "religious": "Religious programming: preaching, prayer, worship or scripture.",
    "advertising": "Advertising, sponsorship or promotion of a product, service or event.",
    "music_entertainment": "Music, comedy, sports or other entertainment.",
    "call_in_conversation": "A listener call-in, interview or informal conversation.",
    "other": "Anything else.",
}
# Content types that rarely carry a checkable claim; the content_type scorer is 1 - their probability.
LOW_CLAIM_TYPES = ("religious", "advertising", "music_entertainment")

LANGUAGE_NOTE = "The transcript may be in Spanish, English, Russian or another language; read it as written."


def _standard_questions() -> dict:
    return {
        "worth_analysis": {
            "type": "noul",
            "instructions": (
                "The radio clip contains a specific factual claim that is false, misleading or unsupported, "
                "and that a fact-checker could check against evidence. " + LANGUAGE_NOTE
            ),
            "criteria": {
                "true": "At least one specific claim is false, misleading or unsupported and could be checked.",
                "false": "No such claim: the clip is accurate, opinion, vague, or has nothing checkable.",
            },
        },
        "checkable_claim": {
            "type": "noul",
            "instructions": (
                "The radio clip states at least one specific, checkable factual claim about the world. "
                "Opinion, prayer, advertising, music, greetings and small talk do not count. " + LANGUAGE_NOTE
            ),
            "criteria": {
                "true": "There is at least one specific factual claim that evidence could confirm or refute.",
                "false": "There are only opinions, prayers, ads, music, greetings or small talk.",
            },
        },
        "stage3_band": {
            "type": "score",
            "instructions": (
                "How clearly does the radio clip spread false or misleading factual claims? Judge only "
                "factual accuracy, not tone, politics or whether you agree. " + LANGUAGE_NOTE
            ),
            "criteria": [
                "No disinformation content: no checkable claims, or the claims are accurate, or it is opinion.",
                "Claims that are vague, exaggerated or unsubstantiated, but nothing clearly contradicts them.",
                "Misleading claims: real facts presented deceptively or with crucial context left out.",
                "Specific claims that available evidence probably contradicts, though not definitively.",
                "Clear, verifiable disinformation: specific claims that reputable sources clearly contradict.",
            ],
        },
        "content_type": {
            "type": "choice",
            "instructions": "What kind of radio content is this clip? " + LANGUAGE_NOTE,
            "criteria": dict(CONTENT_TYPES),
        },
        "harm_topic": {
            "type": "noul",
            "instructions": (
                "The radio clip promotes a conspiracy theory, a health claim that contradicts medical "
                "consensus, false claims about elections or voting, or dehumanizing claims about a group. "
                + LANGUAGE_NOTE
            ),
            "criteria": {
                "true": "The clip promotes at least one of these.",
                "false": "The clip promotes none of these (reporting on them neutrally does not count).",
            },
        },
    }


def _neutral_questions() -> dict:
    """Claim-centric wording for web-grounded models: no 'misinformation', 'disinformation' or 'fact-check'."""
    questions = _standard_questions()
    questions["worth_analysis"]["instructions"] = (
        "The text makes a specific factual claim about the world that is false, misleading or not supported "
        "by reliable evidence, and that could be checked against evidence. " + LANGUAGE_NOTE
    )
    questions["stage3_band"]["instructions"] = (
        "How far do the specific factual claims in the text depart from what reliable evidence shows? Judge "
        "only factual accuracy, not tone, politics or opinion. " + LANGUAGE_NOTE
    )
    questions["stage3_band"]["criteria"] = [
        "No departure: no checkable claims, or the claims are accurate, or it is opinion.",
        "Claims that are vague, exaggerated or unsubstantiated, but nothing clearly contradicts them.",
        "Claims that present real facts deceptively or leave out crucial context.",
        "Specific claims that available evidence probably contradicts, though not definitively.",
        "Specific claims that reliable sources clearly contradict.",
    ]
    questions["checkable_claim"]["instructions"] = (
        "The text states at least one specific, checkable factual claim about the world. Opinion, prayer, "
        "advertising, music, greetings and small talk do not count. " + LANGUAGE_NOTE
    )
    questions["harm_topic"]["instructions"] = (
        "The text promotes a conspiracy theory, a health claim that contradicts medical consensus, false "
        "claims about elections or voting, or dehumanizing claims about a group. " + LANGUAGE_NOTE
    )
    return questions


QUESTION_SETS = {"standard": _standard_questions, "neutral": _neutral_questions}


def questions_for(name: str) -> dict:
    if name not in QUESTION_SETS:
        raise ValueError(f"unknown question set {name!r}; choose from {sorted(QUESTION_SETS)}")
    return QUESTION_SETS[name]()


def questions_hash(questions: dict) -> str:
    return hashlib.sha256(json.dumps(questions, sort_keys=True).encode()).hexdigest()[:10]


def score_levels(question: dict) -> int:
    criteria = question.get("criteria") or []
    return len(criteria) if isinstance(criteria, list) else 0


def scorer_values(answers: dict) -> dict[str, float | None]:
    """Turn normalized answers into per-question gate scorers (higher = run Stage 3); None = missing."""
    values: dict[str, float | None] = {}
    for name, answer in answers.items():
        if answer is None or (answer.get("value") is None and answer.get("type") != "choice"):
            values[name] = None
            continue
        if answer.get("type") == "choice":
            probs = answer.get("probabilities") or {}
            if probs:
                values[name] = 1.0 - sum(float(probs.get(t) or 0.0) for t in LOW_CLAIM_TYPES)
            elif answer.get("choice"):
                values[name] = 0.0 if answer["choice"] in LOW_CLAIM_TYPES else 1.0
            else:
                values[name] = None
        else:
            values[name] = float(answer["value"])
    return values


def stack_features(answers: dict, questions: dict) -> list[float] | None:
    """Dense features for the stacked scorer, or None when any question is missing (never skip)."""
    features: list[float] = []
    for name in sorted(questions):
        q = questions[name]
        answer = answers.get(name)
        if not answer or answer.get("refused"):
            return None
        if q["type"] == "choice":
            probs = answer.get("probabilities") or {}
            if not probs and not answer.get("choice"):
                return None
            for label in sorted(q["criteria"]):
                if probs:
                    features.append(float(probs.get(label) or 0.0))
                else:
                    features.append(1.0 if answer.get("choice") == label else 0.0)
        else:
            if answer.get("value") is None:
                return None
            features.append(float(answer["value"]))
    return features


def shuffle_choices(questions: dict, seed_key: str) -> dict:
    """Copy of ``questions`` with each choice's options in a deterministic per-clip order.

    Jev leans toward the option listed first; shuffling per clip spreads that bias instead of always
    favoring the same label. Label names are unchanged, so scoring does not depend on the order.
    """
    out = {}
    for name, q in questions.items():
        q = dict(q)
        if q.get("type") == "choice" and isinstance(q.get("criteria"), dict):
            labels = sorted(q["criteria"])
            seed = int(hashlib.sha256(f"{seed_key}|{name}".encode()).hexdigest()[:16], 16)
            random.Random(seed).shuffle(labels)
            q["criteria"] = {label: q["criteria"][label] for label in labels}
        out[name] = q
    return out
