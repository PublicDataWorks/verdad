"""Pure metric and model tests for the VER-475 pre-check harness (no network)."""

import math

import pytest

from src.scripts.precheck_eval import metrics as m
from src.scripts.precheck_eval.logreg import fit_logistic, fold_of, sigmoid


# ---------------------------------------------------------------- bands and recall


def test_band_index_edges():
    assert m.band_index(0) == 0
    assert m.band_index(39.9) == 1
    assert m.band_index(80) == 4
    assert m.band_index(89) == 4
    assert m.band_index(90) == 5
    assert m.band_index(100) == 5
    assert m.band_index(150) == 5
    assert m.band_index(-5) == 0
    assert m.band_name(5) == "90-100"
    assert m.bands_at_or_above(80) == [4, 5]


def test_is_skipped_rules():
    assert m.is_skipped(0.1, 0.5)
    assert not m.is_skipped(0.5, 0.5)  # ties at the threshold are kept
    assert not m.is_skipped(None, 0.5)  # missing never skipped
    assert not m.is_skipped(0.1, None)  # no threshold skips nothing


def test_weighted_recall_uses_weights_and_handles_empty_class():
    scores = [0.1, 0.9, 0.2]
    labels = [85, 85, 10]
    weights = [3.0, 1.0, 1.0]
    assert m.weighted_recall(scores, labels, weights, 0.5, 80) == pytest.approx(0.25)
    assert m.weighted_recall(scores, labels, weights, 0.5, 90) is None


# ---------------------------------------------------------------- threshold selection


def test_select_threshold_picks_highest_feasible():
    scores = [0.1, 0.2, 0.3, 0.8, 0.9]
    labels = [0, 10, 20, 85, 95]
    weights = [1.0] * 5
    assert m.select_threshold(scores, labels, weights) == 0.8


def test_select_threshold_ties_are_skipped_together():
    # The 90+ clip shares score 0.3 with a low clip; the threshold cannot split the tie.
    scores = [0.1, 0.3, 0.3, 0.9]
    labels = [0, 0, 95, 85]
    t = m.select_threshold(scores, labels, [1.0] * 4)
    assert t == 0.3
    skipped = [m.is_skipped(s, t) for s in scores]
    assert skipped == [True, False, False, False]


def test_select_threshold_missing_values_never_skipped_and_ignored():
    scores = [None, 0.1, 0.5, 0.6]
    labels = [95, 0, 10, 85]
    t = m.select_threshold(scores, labels, [1.0] * 4)
    assert t == 0.6
    assert not m.is_skipped(None, t)


def test_select_threshold_no_feasible_threshold_skips_nothing():
    # The lowest-scored clip is 90+, so nothing can be skipped.
    scores = [0.05, 0.5, 0.9]
    labels = [95, 0, 10]
    assert m.select_threshold(scores, labels, [1.0] * 3) is None
    assert m.select_threshold([], [], []) is None
    assert m.select_threshold([None, None], [95, 0], [1, 1]) is None


def test_select_threshold_allows_five_percent_loss_of_80_plus():
    # 20 clips at 80-89 with weight 1; losing one (5%) is allowed, losing two is not.
    scores = [i / 100 for i in range(20)] + [0.5]
    labels = [85] * 20 + [0]
    t = m.select_threshold(scores, labels, [1.0] * 21)
    assert t == 0.01
    strict = m.select_threshold(scores, labels, [1.0] * 21, min_recall_80=0.98)
    assert strict is None


def test_select_threshold_respects_weights():
    scores = [0.1, 0.2, 0.9]
    labels = [85, 0, 85]
    # The low 80+ clip carries most of the weight, so skipping it breaks the bar.
    assert m.select_threshold(scores, labels, [10.0, 1.0, 1.0]) is None
    assert m.select_threshold(scores, labels, [0.01, 1.0, 1.0]) == 0.9


# ---------------------------------------------------------------- operating point metrics


def test_point_metrics_counts_and_band_shares():
    skipped = [True, True, False, False, True]
    labels = [0, 30, 85, 95, 82]
    weights = [2.0, 1.0, 1.0, 1.0, 1.0]
    out = m.point_metrics(skipped, labels, weights)
    assert out["skip_rate"] == pytest.approx(4 / 6)
    assert out["recall_80"] == pytest.approx(2 / 3)
    assert out["recall_90"] == 1.0
    assert out["n_lost_80"] == 1 and out["n_lost_90"] == 0
    assert out["n_80"] == 3 and out["n_90"] == 1
    assert out["skipped_share_0-19"] == pytest.approx(0.5)
    assert out["skipped_share_80-89"] == pytest.approx(0.25)
    assert out["recall_90_lb95"] == pytest.approx(0.05)
    assert 0 < out["recall_80_lb95"] < 2 / 3


def test_point_metrics_empty():
    out = m.point_metrics([], [], [])
    assert out["skip_rate"] is None and out["recall_80"] is None and out["recall_80_lb95"] is None


def test_metrics_with_ci_is_deterministic_and_brackets_point():
    skipped = [i % 3 == 0 for i in range(60)]
    labels = [85 if i % 4 == 0 else 10 for i in range(60)]
    weights = [1.0 + (i % 2) for i in range(60)]
    a = m.metrics_with_ci(skipped, labels, weights, samples=200, seed=7)
    b = m.metrics_with_ci(skipped, labels, weights, samples=200, seed=7)
    assert a == b
    sr = a["skip_rate"]
    assert sr["lo"] <= sr["value"] <= sr["hi"]
    assert a["recall_80_lb95"]["lo"] is None


def test_metrics_with_ci_without_samples():
    out = m.metrics_with_ci([False], [95], [1.0], samples=0)
    assert out["recall_90"]["value"] == 1.0 and out["recall_90"]["lo"] is None


def test_percentile_and_quantile():
    assert m.percentile([1, 2, 3, 4], 0.5) == 2.5
    assert m.quantile([], 0.5) is None
    assert m.quantile([5.0], 0.95) == 5.0


# ---------------------------------------------------------------- lower bounds


def test_recall_lower_bound_known_values():
    assert m.recall_lower_bound(0, 0) is None
    assert m.recall_lower_bound(0, 10) == 0.0
    # zero misses: alpha ** (1/n), close to the rule of three
    assert m.recall_lower_bound(24, 24) == pytest.approx(0.05 ** (1 / 24))
    assert m.recall_lower_bound(100, 100) == pytest.approx(1 - 3 / 100, abs=0.005)
    # Clopper-Pearson one-sided 95% for 9/10 is 0.606
    assert m.recall_lower_bound(9, 10) == pytest.approx(0.6058, abs=1e-3)


def test_binomial_upper_tail_edges():
    assert m.binomial_upper_tail(0, 5, 0.3) == 1.0
    assert m.binomial_upper_tail(2, 5, 0.0) == 0.0
    assert m.binomial_upper_tail(2, 5, 1.0) == 1.0
    assert m.binomial_upper_tail(5, 5, 0.5) == pytest.approx(1 / 32)


# ---------------------------------------------------------------- threshold-free


def test_weighted_auroc_perfect_ties_and_missing():
    labels = [90, 85, 10, 0]
    w = [1.0] * 4
    assert m.weighted_auroc([0.9, 0.8, 0.2, 0.1], labels, w, lambda y: y >= 80, lambda y: y < 40) == 1.0
    assert m.weighted_auroc([0.5] * 4, labels, w, lambda y: y >= 80, lambda y: y < 40) == 0.5
    # Missing scores rank highest.
    assert m.weighted_auroc([None, None, 0.2, 0.1], labels, w, lambda y: y >= 80, lambda y: y < 40) == 1.0
    assert m.weighted_auroc([0.1, 0.2], [0, 0], [1, 1], lambda y: y >= 80, lambda y: y < 40) is None


def test_weighted_auroc_weights_matter():
    scores = [0.9, 0.1, 0.5]
    labels = [85, 85, 0]
    unweighted = m.weighted_auroc(scores, labels, [1, 1, 1], lambda y: y >= 80, lambda y: y < 80)
    weighted = m.weighted_auroc(scores, labels, [1, 3, 1], lambda y: y >= 80, lambda y: y < 80)
    assert unweighted == 0.5 and weighted == pytest.approx(0.25)


def test_recall_at_skip_rates():
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, None]
    labels = [0, 0, 0, 85, 0, 0, 0, 95, 0, 85]
    out = m.recall_at_skip_rates(scores, labels, [1.0] * 10, (0.3, 0.5, 0.95))
    assert out[0]["skip_rate"] == pytest.approx(0.3) and out[0]["recall_80"] == 1.0
    assert out[1]["recall_80"] == pytest.approx(2 / 3)
    assert out[2]["skip_rate"] == pytest.approx(0.9)  # the missing clip is never skipped
    tied = m.recall_at_skip_rates([0.5] * 4, [0, 0, 85, 0], [1.0] * 4, (0.5,))
    assert tied[0]["skip_rate"] == 0.0


def test_group_metrics():
    out = m.group_metrics([True, False, True], [0, 85, 95], [1.0, 1.0, 2.0], ["a", "a", "b"])
    assert out["a"]["skip_rate"] == 0.5 and out["a"]["weight_share"] == 0.5
    assert out["b"]["recall_90"] == 0.0


# ---------------------------------------------------------------- logistic regression


def test_fit_logistic_separates_and_is_deterministic():
    X = [{0: float(i)} for i in range(20)]
    y = [1.0 if i >= 10 else 0.0 for i in range(20)]
    a = fit_logistic(X, y, standardize=True, seed=3)
    b = fit_logistic(X, y, standardize=True, seed=3)
    assert a.weights == b.weights and a.bias == b.bias
    assert a.predict({0: 19.0}) > 0.8 > 0.2 > a.predict({0: 0.0})


def test_fit_logistic_edge_cases():
    assert fit_logistic([], []).predict({0: 1.0}) == 0.5
    with pytest.raises(ValueError):
        fit_logistic([{0: 1.0}], [])
    constant = fit_logistic([{0: 1.0}] * 4, [0.0, 0.0, 1.0, 1.0], standardize=True)
    assert 0.3 < constant.predict({0: 1.0}) < 0.7
    strong = fit_logistic([{0: 1.0}, {1: 1.0}], [1.0, 0.0], l2=100.0, epochs=5)
    assert abs(strong.weights[0]) < 5


def test_sigmoid_is_stable():
    assert sigmoid(1000) == pytest.approx(1.0)
    assert sigmoid(-1000) == pytest.approx(0.0, abs=1e-20)
    assert sigmoid(0) == 0.5
    assert not math.isnan(sigmoid(-800))


def test_fold_of_is_stable_and_spread():
    folds = [fold_of(f"id-{i}", 5) for i in range(200)]
    assert fold_of("id-1", 5) == folds[1]
    assert set(folds) == {0, 1, 2, 3, 4}
