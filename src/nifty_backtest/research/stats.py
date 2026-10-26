"""Statistics for M7 comparisons (pre-registration sections 6-7). Standard library only.

- Paired t-test: t = mean(d) / (sd(d) / sqrt(n)), two-sided p from Student's t with n - 1
  degrees of freedom. The p-value uses the regularised incomplete beta function:
      p = I_x(df / 2, 1 / 2),  x = df / (df + t^2)
  evaluated with the continued fraction of Numerical Recipes (Press et al., "betacf").
- Holm-Bonferroni: sort the m p-values ascending, multiply the k-th smallest by (m - k + 1),
  keep the running maximum (so adjusted values never decrease), cap at 1.
- Bootstrap of a mean, percentile interval, fixed seed:
    i.i.d.        resample the n values with replacement;
    moving-block  circular blocks of `block` consecutive values, enough to make n; keeps
                  runs of neighbouring weeks together, so serial dependence (volatility
                  clustering) widens the interval instead of being ignored.
- Lag-1 autocorrelation: how much one week's value resembles the next week's.
"""

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz's method)."""
    tiny, eps = 1e-300, 3e-16
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < eps:
            return h
    raise ArithmeticError("incomplete beta continued fraction did not converge")


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b) for 0 <= x <= 1."""
    if not 0 <= x <= 1:
        raise ValueError("x must be in [0, 1]")
    if x in (0.0, 1.0):
        return x
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    # The continued fraction converges fastest on this side of the mean a / (a + b).
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_two_sided_p(t: float, df: float) -> float:
    """Two-sided p-value of Student's t statistic with `df` degrees of freedom."""
    return betainc(df / 2, 0.5, df / (df + t * t))


@dataclass(frozen=True)
class PairedTest:
    n: int
    mean: float
    sd: float | None
    t: float | None
    p: float | None  # None when it cannot be computed (n < 2, or no spread)


def paired_t_test(differences: Sequence[float]) -> PairedTest:
    n = len(differences)
    if n == 0:
        return PairedTest(0, math.nan, None, None, None)
    mean = statistics.fmean(differences)
    if n < 2:
        return PairedTest(n, mean, None, None, None)
    sd = statistics.stdev(differences)
    if sd == 0:
        return PairedTest(n, mean, 0.0, None, None)
    t = mean / (sd / math.sqrt(n))
    return PairedTest(n, mean, sd, t, t_two_sided_p(t, n - 1))


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm-Bonferroni adjusted p-values for one family of tests."""
    ordered = sorted(pvalues.items(), key=lambda item: item[1])
    m = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for k, (name, p) in enumerate(ordered):
        running = max(running, min(1.0, (m - k) * p))
        adjusted[name] = running
    return adjusted


def _percentile_interval(means: list[float], level: float) -> tuple[float, float]:
    # statistics.quantiles with method="inclusive" interpolates linearly between order
    # statistics; with n=200 cut points, index 4 is the 2.5th and index 194 the 97.5th
    # percentile for level 0.95.
    cuts = statistics.quantiles(means, n=200, method="inclusive")
    tail = round((1 - level) / 2 * 200)
    return cuts[tail - 1], cuts[200 - tail - 1]


def bootstrap_mean_interval(
    values: Sequence[float],
    resamples: int,
    seed: int,
    block: int | None = None,
    level: float = 0.95,
) -> tuple[float, float] | None:
    """Percentile bootstrap interval for the mean (i.i.d., or circular moving blocks)."""
    n = len(values)
    if n < 2:
        return None
    rng = random.Random(seed)
    data = list(values)
    means = []
    for _ in range(resamples):
        if block is None or block <= 1:
            sample = rng.choices(data, k=n)
        else:
            sample = []
            while len(sample) < n:
                start = rng.randrange(n)
                sample.extend(data[(start + i) % n] for i in range(block))
            sample = sample[:n]
        means.append(statistics.fmean(sample))
    return _percentile_interval(means, level)


def lag1_autocorrelation(values: Sequence[float]) -> float | None:
    """Correlation between consecutive values (None if it cannot be computed)."""
    if len(values) < 3:
        return None
    mean = statistics.fmean(values)
    centred = [v - mean for v in values]
    denominator = sum(c * c for c in centred)
    if denominator == 0:
        return None
    return sum(a * b for a, b in pairwise(centred)) / denominator


def worst_share_mean(values: Sequence[float], share: float = 0.05) -> float | None:
    """Mean of the worst `share` of values (at least one value): a simple tail measure."""
    if not values:
        return None
    count = max(1, math.ceil(share * len(values)))
    return statistics.fmean(sorted(values)[:count])
