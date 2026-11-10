"""Pure, weighted metrics for a skip gate in front of Stage 3.

A *gate scorer* gives each clip a float where higher means "run Stage 3"; ``None`` means the answer is
missing (refusal, error) and the clip is never skipped. At threshold ``t`` a clip is skipped when its score
is below ``t``; ``t = None`` skips nothing. Every population number is weighted by the clip's inverse
sampling probability. Labels are Stage 3 overall scores (0-100).
"""

import math
import random

from .config import SCORE_BANDS

EPS = 1e-12


def band_index(label: float) -> int:
    for i, (lo, hi) in enumerate(SCORE_BANDS):
        if lo <= label < hi:
            return i
    return 0 if label < SCORE_BANDS[0][0] else len(SCORE_BANDS) - 1


def band_name(i: int) -> str:
    lo, hi = SCORE_BANDS[i]
    return f"{lo}-{min(hi, 101) - 1}"


def bands_at_or_above(cutoff: float) -> list[int]:
    """Band indices whose lower edge is >= cutoff (cutoffs must be band edges, e.g. 80 and 90)."""
    return [i for i, (lo, _) in enumerate(SCORE_BANDS) if lo >= cutoff]


def is_skipped(score: float | None, threshold: float | None) -> bool:
    return threshold is not None and score is not None and score < threshold


# --------------------------------------------------------------------------------------
# Threshold selection
# --------------------------------------------------------------------------------------


def weighted_recall(scores, labels, weights, threshold, cutoff: float) -> float | None:
    """Weighted share of clips with label >= cutoff that are kept; None when there are none."""
    total = kept = 0.0
    for s, y, w in zip(scores, labels, weights, strict=True):
        if y >= cutoff:
            total += w
            if not is_skipped(s, threshold):
                kept += w
    return kept / total if total > 0 else None


def select_threshold(scores, labels, weights, min_recall_80: float = 0.95, min_recall_90: float = 1.0):
    """Highest observed score ``t`` such that skipping clips with score < t keeps weighted recall of
    label >= 90 at ``min_recall_90`` and of label >= 80 at ``min_recall_80``.

    Ties are skipped or kept together. Returns None ("skip nothing") when the best feasible threshold is
    the lowest observed score, which skips nothing here and must not skip anything elsewhere either.
    A recall constraint with no clips in its class is treated as met.
    """
    tot80 = sum(w for y, w in zip(labels, weights, strict=True) if y >= 80)
    tot90 = sum(w for y, w in zip(labels, weights, strict=True) if y >= 90)
    items = sorted(
        ((s, y, w) for s, y, w in zip(scores, labels, weights, strict=True) if s is not None), key=lambda t: t[0]
    )
    best = None
    lost80 = lost90 = 0.0
    i = 0
    first = True
    while i < len(items):
        value = items[i][0]
        r80 = 1.0 - lost80 / tot80 if tot80 > 0 else 1.0
        r90 = 1.0 - lost90 / tot90 if tot90 > 0 else 1.0
        if r80 + EPS < min_recall_80 or r90 + EPS < min_recall_90:
            break
        best = None if first else value
        while i < len(items) and items[i][0] == value:
            _, y, w = items[i]
            if y >= 80:
                lost80 += w
            if y >= 90:
                lost90 += w
            i += 1
        first = False
    return best


# --------------------------------------------------------------------------------------
# Operating-point metrics with bootstrap CIs
# --------------------------------------------------------------------------------------


def _accumulate(indices, skipped, bands, weights):
    n_bands = len(SCORE_BANDS)
    acc = [[0.0] * n_bands, [0.0] * n_bands]
    cnt = [[0] * n_bands, [0] * n_bands]
    for i in indices:
        k = 1 if skipped[i] else 0
        b = bands[i]
        acc[k][b] += weights[i]
        cnt[k][b] += 1
    return acc, cnt


def _from_acc(acc, cnt) -> dict:
    hi80, hi90 = bands_at_or_above(80), bands_at_or_above(90)
    kept_w, skip_w = sum(acc[0]), sum(acc[1])
    total = kept_w + skip_w

    def recall(bs):
        denom = sum(acc[0][b] + acc[1][b] for b in bs)
        return sum(acc[0][b] for b in bs) / denom if denom > 0 else None

    out = {
        "skip_rate": skip_w / total if total > 0 else None,
        "recall_90": recall(hi90),
        "recall_80": recall(hi80),
        "n_lost_90": sum(cnt[1][b] for b in hi90),
        "n_lost_80": sum(cnt[1][b] for b in hi80),
        "n_skipped": sum(cnt[1]),
        "n": sum(cnt[0]) + sum(cnt[1]),
        "n_90": sum(cnt[0][b] + cnt[1][b] for b in hi90),
        "n_80": sum(cnt[0][b] + cnt[1][b] for b in hi80),
    }
    for b in range(len(SCORE_BANDS)):
        out[f"skipped_share_{band_name(b)}"] = acc[1][b] / skip_w if skip_w > 0 else None
    return out


def binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    log_p, log_q = math.log(p), math.log1p(-p)
    total = 0.0
    for i in range(k, n + 1):
        total += math.exp(
            math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * log_p + (n - i) * log_q
        )
    return min(1.0, total)


def recall_lower_bound(kept: int, total: int, alpha: float = 0.05) -> float | None:
    """One-sided (1 - alpha) Clopper-Pearson lower bound on a proportion, from unweighted counts.

    With zero misses it is alpha ** (1 / n) (about 1 - 3/n, the rule of three). None when total is 0.
    """
    if total <= 0:
        return None
    if kept <= 0:
        return 0.0
    if kept >= total:
        return alpha ** (1.0 / total)
    lo, hi = 0.0, kept / total
    for _ in range(60):
        mid = (lo + hi) / 2
        if binomial_upper_tail(kept, total, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return lo


def _lower_bounds(point: dict) -> dict:
    return {
        "recall_90_lb95": recall_lower_bound(point["n_90"] - point["n_lost_90"], point["n_90"]),
        "recall_80_lb95": recall_lower_bound(point["n_80"] - point["n_lost_80"], point["n_80"]),
    }


def point_metrics(skipped, labels, weights) -> dict:
    """Weighted operating-point metrics plus unweighted one-sided 95% lower bounds on recall."""
    bands = [band_index(y) for y in labels]
    point = _from_acc(*_accumulate(range(len(labels)), skipped, bands, weights))
    point.update(_lower_bounds(point))
    return point


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def metrics_with_ci(skipped, labels, weights, samples: int = 1000, seed: int = 0) -> dict:
    """Point metrics plus percentile bootstrap 95% CIs (clips resampled with replacement, fixed seed).

    The threshold is held fixed, so the interval covers sampling noise in the evaluated split only.
    Returns ``{metric: {"value", "lo", "hi"}}``; lo/hi are None when too few replicates define the metric.
    ``recall_*_lb95`` are one-sided Clopper-Pearson bounds from unweighted counts (no bootstrap).
    """
    n = len(labels)
    bands = [band_index(y) for y in labels]
    point = _from_acc(*_accumulate(range(n), skipped, bands, weights))
    draws: dict[str, list[float]] = {k: [] for k in point}
    if n and samples > 0:
        rng = random.Random(seed)
        for _ in range(samples):
            idx = [rng.randrange(n) for _ in range(n)]
            rep = _from_acc(*_accumulate(idx, skipped, bands, weights))
            for k, v in rep.items():
                if v is not None:
                    draws[k].append(v)
    out = {k: {"value": v, "lo": None, "hi": None} for k, v in _lower_bounds(point).items()}
    for k, v in point.items():
        values = draws[k]
        enough = len(values) >= max(2, samples // 2)
        out[k] = {
            "value": v,
            "lo": percentile(values, 0.025) if enough else None,
            "hi": percentile(values, 0.975) if enough else None,
        }
    return out


# --------------------------------------------------------------------------------------
# Threshold-free metrics
# --------------------------------------------------------------------------------------


def _ordered_groups(scores, *columns):
    """Rows sorted by score ascending (missing = +inf, never skipped), grouped by equal score."""
    rows = sorted(zip(scores, *columns, strict=True), key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0))
    groups, current, key = [], [], object()
    for row in rows:
        k = ("inf",) if row[0] is None else (row[0],)
        if current and k != key:
            groups.append(current)
            current = []
        current.append(row)
        key = k
    if current:
        groups.append(current)
    return groups


def weighted_auroc(scores, labels, weights, is_positive, is_negative) -> float | None:
    """P(score of a random positive > score of a random negative), weighted, ties count half.

    Clips that are neither positive nor negative are ignored. Missing scores rank highest (never skip).
    """
    pos_total = sum(w for y, w in zip(labels, weights, strict=True) if is_positive(y))
    neg_total = sum(w for y, w in zip(labels, weights, strict=True) if is_negative(y))
    if pos_total <= 0 or neg_total <= 0:
        return None
    area = 0.0
    neg_below = 0.0
    for group in _ordered_groups(scores, labels, weights):
        pos_w = sum(w for _, y, w in group if is_positive(y))
        neg_w = sum(w for _, y, w in group if is_negative(y))
        area += pos_w * (neg_below + 0.5 * neg_w)
        neg_below += neg_w
    return area / (pos_total * neg_total)


def recall_at_skip_rates(scores, labels, weights, rates) -> list[dict]:
    """Skip the lowest-scoring clips up to each target weighted skip rate (whole tie groups only)."""
    total = sum(weights)
    groups = _ordered_groups(scores, labels, weights)
    out = []
    for rate in rates:
        skipped_ids = set()
        cum = 0.0
        index = 0
        for group in groups:
            if group[0][0] is None:
                break
            group_w = sum(w for _, _, w in group)
            if cum + group_w > rate * total + EPS:
                break
            cum += group_w
            for _ in group:
                skipped_ids.add(index)
                index += 1
        flat = [row for group in groups for row in group]
        skipped = [i in skipped_ids for i in range(len(flat))]
        m = point_metrics(skipped, [r[1] for r in flat], [r[2] for r in flat])
        out.append(
            {"target": rate, "skip_rate": m["skip_rate"], "recall_80": m["recall_80"], "recall_90": m["recall_90"]}
        )
    return out


def group_metrics(skipped, labels, weights, keys) -> dict:
    """Operating-point metrics per group key (e.g. station or language), plus the group's weight share."""
    total = sum(weights)
    groups: dict = {}
    for i, key in enumerate(keys):
        groups.setdefault(key, []).append(i)
    out = {}
    for key, idx in groups.items():
        m = point_metrics([skipped[i] for i in idx], [labels[i] for i in idx], [weights[i] for i in idx])
        m["weight_share"] = sum(weights[i] for i in idx) / total if total > 0 else None
        out[key] = m
    return out


def quantile(values: list[float], q: float) -> float | None:
    return percentile(values, q) if values else None
