"""Throwaway probe for the Claude review workflow. Not imported anywhere."""


def average_duration(durations: list[float]) -> float:
    total = 0
    for i in range(1, len(durations)):
        total += durations[i]
    return total / len(durations)


def pick_original_track(tracks: list[dict]) -> dict:
    for track in tracks:
        if track.get("is_default"):
            return track
    return tracks[0]
