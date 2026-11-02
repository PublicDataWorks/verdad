"""Temporal context shared by the Stage 1, 3 and 4 model prompts.

Every stage tells the model what "now" is, how old the recording is, and that its training data ends before
many recent events, so that an unfamiliar claim is treated as unknown rather than false.
"""

from datetime import datetime, timezone

HUMAN_DATETIME_FORMAT = "%B %d, %Y %I:%M %p"  # e.g. "March 05, 2026 09:07 AM" (also parses "March 5, 2026 9:07 AM")
BREAKING_NEWS_TIERS = ((24, 20), (72, 30))  # (max age in hours, max confidence score)
BREAKING_NEWS_WINDOW_HOURS = BREAKING_NEWS_TIERS[-1][0]


def temporal_notice(now: datetime) -> str:
    return (
        f"Today is {now.strftime('%B %d, %Y')} (UTC). Your training data ends before many recent events; "
        "a claim about something you do not recognize is UNKNOWN, not false."
    )


def parse_recorded_at(value) -> datetime | None:
    """Parse an ISO 8601 timestamp or the human-readable metadata format into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(value, HUMAN_DATETIME_FORMAT)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def hours_between(recorded_at: datetime | None, now: datetime) -> float | None:
    if recorded_at is None:
        return None
    return round((now - recorded_at).total_seconds() / 3600, 1)


def breaking_news_notice(hours_since_recording: float | None) -> str:
    """Render the breaking-news cap that applies to a recording of this age, or "" when none applies."""
    if hours_since_recording is None:
        return ""
    for max_hours, max_score in BREAKING_NEWS_TIERS:
        if hours_since_recording <= max_hours:
            return (
                f"**BREAKING NEWS PROTOCOL APPLIES**: This recording is {hours_since_recording} hours old "
                f"(< {max_hours} hours). Maximum confidence score is {max_score} unless contradictory evidence "
                f"from tier-1/tier-2 sources is found. Use verification_status: insufficient_evidence."
            )
    return ""


def build_temporal_context(recorded_at, now: datetime | None = None) -> dict:
    """Compute everything a prompt needs to reason about time.

    Args:
        recorded_at: ISO 8601 string, the human-readable metadata string, an aware datetime, or None.
        now: Current time (defaults to UTC now).

    Returns:
        dict with current_date_time (human string), hours_since_recording (str, "" if unknown),
        breaking_news_notice (str, "" if none) and temporal_notice (str).
    """
    now = now or datetime.now(timezone.utc)
    recorded_dt = recorded_at if isinstance(recorded_at, datetime) else parse_recorded_at(recorded_at)
    hours = hours_between(recorded_dt, now)
    return {
        "current_date_time": now.strftime(f"{HUMAN_DATETIME_FORMAT} UTC"),
        "hours_since_recording": "" if hours is None else str(hours),
        "breaking_news_notice": breaking_news_notice(hours),
        "temporal_notice": temporal_notice(now),
    }
