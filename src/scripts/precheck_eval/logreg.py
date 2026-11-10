"""A small, deterministic, L2-regularized logistic regression in pure Python (numpy is not installed).

Features are sparse dicts ``{index: value}``. Training is seeded Adagrad SGD over a fixed number of
epochs; the L2 penalty is applied to a weight each time its feature is active (the usual sparse-SGD
convention), the bias is not penalized. ``standardize=True`` z-scores dense features using training
statistics; leave it off for hashed text features.
"""

import hashlib
import math
import random
from dataclasses import dataclass, field

Features = dict[int, float]


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 50.0)))
    e = math.exp(max(z, -50.0))
    return e / (1.0 + e)


@dataclass
class LogisticModel:
    weights: dict[int, float] = field(default_factory=dict)
    bias: float = 0.0
    means: dict[int, float] = field(default_factory=dict)
    scales: dict[int, float] = field(default_factory=dict)

    def transform(self, x: Features) -> Features:
        if not self.scales:
            return x
        return {j: (v - self.means.get(j, 0.0)) / self.scales.get(j, 1.0) for j, v in x.items()}

    def decision(self, x: Features) -> float:
        z = self.bias
        for j, v in self.transform(x).items():
            z += self.weights.get(j, 0.0) * v
        return z

    def predict(self, x: Features) -> float:
        return sigmoid(self.decision(x))


def _standardization(X: list[Features]) -> tuple[dict[int, float], dict[int, float]]:
    n = len(X)
    sums: dict[int, float] = {}
    sq: dict[int, float] = {}
    for x in X:
        for j, v in x.items():
            sums[j] = sums.get(j, 0.0) + v
            sq[j] = sq.get(j, 0.0) + v * v
    means = {j: s / n for j, s in sums.items()}
    scales = {}
    for j in sums:
        var = sq[j] / n - means[j] ** 2
        scales[j] = math.sqrt(var) if var > 1e-12 else 1.0
    return means, scales


def fit_logistic(
    X: list[Features],
    y: list[float],
    l2: float = 1.0,
    epochs: int = 40,
    learning_rate: float = 0.3,
    seed: int = 0,
    standardize: bool = False,
) -> LogisticModel:
    if len(X) != len(y):
        raise ValueError("X and y differ in length")
    model = LogisticModel()
    if not X:
        return model
    if standardize:
        model.means, model.scales = _standardization(X)
    rows = [model.transform(x) for x in X]
    n = len(rows)
    prior = min(max(sum(y) / n, 1e-3), 1 - 1e-3)
    model.bias = math.log(prior / (1 - prior))
    grad_sq: dict[int, float] = {}
    bias_sq = 1e-8
    penalty = l2 / n
    order = list(range(n))
    rng = random.Random(seed)
    for _ in range(epochs):
        rng.shuffle(order)
        for i in order:
            x = rows[i]
            z = model.bias
            for j, v in x.items():
                z += model.weights.get(j, 0.0) * v
            err = sigmoid(z) - y[i]
            bias_sq += err * err
            model.bias -= learning_rate * err / math.sqrt(bias_sq)
            for j, v in x.items():
                w = model.weights.get(j, 0.0)
                g = err * v + penalty * w
                grad_sq[j] = grad_sq.get(j, 1e-8) + g * g
                model.weights[j] = w - learning_rate * g / math.sqrt(grad_sq[j])
    return model


def fold_of(snippet_id: str, k: int) -> int:
    return int(hashlib.sha1(snippet_id.encode()).hexdigest(), 16) % k
