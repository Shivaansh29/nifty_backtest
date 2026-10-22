"""Metric formulas against hand-calculated examples (spec M4: 'tested against a hand-computed
example'). Every expected number is worked out in the comments."""

import math
from datetime import date

import pandas as pd
import pytest

from nifty_backtest.metrics.stats import (
    cagr,
    daily_rate,
    max_drawdown,
    roi,
    sharpe,
    sortino,
    t_stat,
)

D = [date(2025, 1, d) for d in (1, 2, 3, 6)]
RETURNS = pd.Series([0.01, -0.02, 0.03, 0.00], index=D)
ROOT_252 = math.sqrt(252)  # 15.8745079


def test_sharpe_hand_computed() -> None:
    # mean = (0.01 - 0.02 + 0.03 + 0) / 4 = 0.005
    # deviations 0.005, -0.025, 0.025, -0.005 -> squares sum 0.0013
    # sample sd = sqrt(0.0013 / 3) = 0.0208166600
    # Sharpe = 0.005 / 0.02081666 x sqrt(252) = 0.2401922 x 15.8745079 = 3.81293
    assert sharpe(RETURNS, 0.0, 252).value == pytest.approx(3.81293, abs=1e-5)


def test_sharpe_with_a_target_subtracts_it_every_day() -> None:
    # excess = r - 0.001: mean 0.004, sd unchanged -> 0.004 / 0.02081666 x 15.8745 = 3.05035
    assert sharpe(RETURNS, 0.001, 252).value == pytest.approx(3.05035, abs=1e-5)


def test_sortino_hand_computed() -> None:
    # Only -0.02 is below the 0 target: downside dev = sqrt((0.02^2 + 0 + 0 + 0) / 4) = 0.01
    # Sortino = 0.005 / 0.01 x sqrt(252) = 0.5 x 15.8745079 = 7.93725
    assert sortino(RETURNS, 0.0, 252).value == pytest.approx(7.93725, abs=1e-5)


def test_ratios_refuse_a_series_with_a_gap() -> None:
    gappy = pd.Series([0.01, float("nan"), 0.03, 0.0], index=D)
    for ratio in (sharpe(gappy, 0.0, 252), sortino(gappy, 0.0, 252)):
        assert ratio.value is None
        assert "missing" in ratio.note


def test_zero_spread_and_no_downside_give_none_not_infinity() -> None:
    flat = pd.Series([0.01, 0.01, 0.01], index=D[:3])
    assert sharpe(flat, 0.0, 252).value is None
    always_up = pd.Series([0.01, 0.02], index=D[:2])
    assert sortino(always_up, 0.0, 252).value is None
    assert sharpe(pd.Series([0.01], index=D[:1]), 0.0, 252).value is None  # one day only


def test_daily_rate_is_geometric() -> None:
    # (1.065)^(1/252) - 1: ln(1.065) = 0.0629748; / 252 = 0.0002499; e^x - 1 = 0.00024993
    assert daily_rate(0.065, 252) == pytest.approx(0.00024993, rel=1e-4)
    assert (1 + daily_rate(0.065, 252)) ** 252 == pytest.approx(1.065)


def test_roi_and_cagr() -> None:
    assert roi(779_138.515828, 500_000) == pytest.approx(0.558277031656)
    # 1 Jan 2020 -> 1 Jan 2024 is 1,461 days = 4 x 365.25: 100 -> 146.41 is 1.1^4, so 10%.
    assert cagr(100.0, 146.41, date(2020, 1, 1), date(2024, 1, 1)) == pytest.approx(0.10)
    assert cagr(100.0, 110.0, date(2020, 1, 1), date(2020, 1, 1)) is None


def test_drawdown_hand_computed() -> None:
    # Equity 100 -> 110 -> 99 -> 121, capital 100. Peak 110 (day 2), trough 99 (day 3):
    # fall Rs 11 = 10% of 110. Recovered on day 4 (121 >= 110).
    dd = max_drawdown(pd.Series([100.0, 110.0, 99.0, 121.0], index=D), 100.0)
    assert dd.max_rs == pytest.approx(11.0)
    assert dd.max_pct == pytest.approx(0.10)
    assert (dd.rs_peak_date, dd.rs_trough_date, dd.rs_recovery_date) == (D[1], D[2], D[3])
    assert (dd.lower_bound, dd.note) == (False, "")  # complete series: an exact value


def test_drawdown_in_rupees_and_percent_can_differ() -> None:
    # 200 -> 150 is a Rs 50 / 25% fall; 1000 -> 800 is Rs 200 / 20%. The rupee maximum is the
    # second, the percentage maximum the first.
    dd = max_drawdown(pd.Series([200.0, 150.0, 1000.0, 800.0], index=D), 100.0)
    assert (dd.max_rs, dd.rs_peak_date, dd.rs_trough_date) == (200.0, D[2], D[3])
    assert dd.rs_recovery_date is None  # never back above 1000
    assert (dd.max_pct, dd.pct_peak_date, dd.pct_trough_date) == (0.25, D[0], D[1])
    assert dd.pct_recovery_date == D[2]


def test_drawdown_counts_from_the_starting_capital() -> None:
    # A loss from day one: the peak is the capital itself (no peak date).
    dd = max_drawdown(pd.Series([95.0, 97.0, 100.0], index=D[:3]), 100.0)
    assert (dd.max_rs, dd.rs_peak_date, dd.rs_trough_date, dd.rs_recovery_date) == (
        5.0, None, D[0], D[2],
    )  # fmt: skip


def test_drawdown_reports_missing_days() -> None:
    dd = max_drawdown(pd.Series([100.0, float("nan"), 90.0], index=D[:3]), 100.0)
    assert (dd.max_rs, dd.missing_days) == (10.0, 1)
    # R2: a trough could hide in the gap, so 10 is only what was observed.
    assert dd.lower_bound
    assert dd.note == "observed lower bound: 1 daily values missing"


def test_drawdown_with_a_missing_start_value_is_never_a_silent_zero() -> None:
    # Regression (M4 correction): with start NaN the old code compared every value against
    # NaN, never saw a fall, and reported 0. Now the peak starts at the first observed value:
    # 120 -> 80 is a Rs 40 fall, 40 / 120 = 33.33%.
    dd = max_drawdown(pd.Series([120.0, 80.0, 100.0], index=D[:3]), float("nan"))
    assert dd.max_rs == pytest.approx(40.0)
    assert dd.max_pct == pytest.approx(1 / 3)
    assert (dd.rs_peak_date, dd.rs_trough_date, dd.rs_recovery_date) == (D[0], D[1], None)
    assert dd.lower_bound
    assert "starting value missing" in dd.note


def test_t_stat_hand_computed() -> None:
    # values 2, 4, 6: mean 4, sample sd 2, t = 4 / (2 / sqrt(3)) = 3.4641016
    assert t_stat([2.0, 4.0, 6.0]) == pytest.approx(3.4641016)
    assert t_stat([5.0]) is None  # needs at least 2 trades
    assert t_stat([3.0, 3.0]) is None  # zero spread
