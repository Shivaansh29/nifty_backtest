"""M7 statistics against hand-worked values and published tables."""

import math

import pytest

from nifty_backtest.research.stats import (
    betainc,
    bootstrap_mean_interval,
    holm,
    lag1_autocorrelation,
    paired_t_test,
    t_two_sided_p,
    worst_share_mean,
)


def test_incomplete_beta_closed_forms() -> None:
    # I_x(1, 1) = x; I_x(1, b) = 1 - (1 - x)^b; I_x(a, 1) = x^a.
    assert betainc(1, 1, 0.3) == pytest.approx(0.3)
    assert betainc(1, 3, 0.2) == pytest.approx(1 - 0.8**3)
    assert betainc(2.5, 1, 0.6) == pytest.approx(0.6**2.5)
    assert (betainc(2, 3, 0.0), betainc(2, 3, 1.0)) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("t", "df", "p"),
    [
        (2.228138852, 10, 0.05),  # the textbook 5% critical value for 10 degrees of freedom
        (12.70620474, 1, 0.05),  # 1 degree of freedom
        (2.576, 1e7, 0.01),  # large df -> the normal distribution's 1% value
        (0.0, 20, 1.0),
    ],
)
def test_t_p_values_match_published_tables(t: float, df: float, p: float) -> None:
    assert t_two_sided_p(t, df) == pytest.approx(p, abs=2e-5)


def test_paired_t_test_hand_computed() -> None:
    # d = 1, 2, 3, 4, 5: mean 3, sample sd sqrt(2.5) = 1.5811, t = 3 / (1.5811 / sqrt 5) = 4.2426
    test = paired_t_test([1.0, 2.0, 3.0, 4.0, 5.0])
    assert (test.n, test.mean) == (5, 3.0)
    assert test.t == pytest.approx(4.242640687)
    assert test.p == pytest.approx(t_two_sided_p(4.242640687, 4))
    assert paired_t_test([2.0, 2.0]).p is None  # no spread
    assert paired_t_test([1.0]).t is None


def test_holm_hand_computed() -> None:
    # Sorted: 0.005 x 4 = 0.02; 0.01 x 3 = 0.03; 0.03 x 2 = 0.06; 0.04 x 1 = 0.04 -> kept at
    # the running maximum 0.06.
    adjusted = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.005})
    assert adjusted == pytest.approx({"d": 0.02, "a": 0.03, "c": 0.06, "b": 0.06})
    assert holm({"x": 0.6, "y": 0.7}) == {"x": 1.0, "y": 1.0}  # capped at 1


def test_bootstrap_is_reproducible_and_sensible() -> None:
    values = [float(v) for v in range(20)]  # mean 9.5
    first = bootstrap_mean_interval(values, 2000, seed=7)
    assert first == bootstrap_mean_interval(values, 2000, seed=7)  # same seed, same answer
    assert first is not None
    assert first[0] < 9.5 < first[1]
    blocks = bootstrap_mean_interval(values, 2000, seed=7, block=4)
    assert blocks is not None
    assert blocks[0] < 9.5 < blocks[1]
    assert bootstrap_mean_interval([3.0, 3.0, 3.0], 500, seed=1) == (3.0, 3.0)
    assert bootstrap_mean_interval([1.0], 500, seed=1) is None


def test_block_bootstrap_is_wider_when_weeks_cluster() -> None:
    # Runs of similar values (serial dependence): resampling single weeks breaks the runs up
    # and understates the uncertainty of the mean; blocks of 4 keep them.
    clustered = [5.0] * 10 + [-5.0] * 10 + [5.0] * 10 + [-5.0] * 10
    iid = bootstrap_mean_interval(clustered, 4000, seed=3)
    block = bootstrap_mean_interval(clustered, 4000, seed=3, block=4)
    assert iid is not None
    assert block is not None
    assert block[1] - block[0] > iid[1] - iid[0]
    # Lag-1 autocorrelation: values +-5 around a mean of 0, so the denominator is 40 x 25.
    # Of the 39 neighbour pairs, 36 agree (+25 each) and 3 straddle a switch (-25 each):
    # (36 - 3) x 25 / 1000 = 0.825.
    assert lag1_autocorrelation(clustered) == pytest.approx(0.825)


def test_worst_share_mean() -> None:
    values = [float(v) for v in range(1, 41)]  # 5% of 40 = 2 worst values: 1 and 2
    assert worst_share_mean(values) == 1.5
    assert worst_share_mean([4.0, 9.0]) == 4.0  # at least one value
    assert worst_share_mean([]) is None
    assert math.isnan(paired_t_test([]).mean)
