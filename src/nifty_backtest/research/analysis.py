"""Pairing, statistics and verdicts for one study (M7 pre-registration, sections 6-7).

Everything here works on saved trade logs and metrics, so every number in a study traces back
to run folders on disk.

The comparison unit (pre-registration 6.1): for every expiry the BASELINE traded in a period,
  d_pts = variant net points per unit - baseline net points per unit
          (a week the variant did not trade counts as 0 points: no position, no P&L)
  d_pct = 100 x d_pts / the baseline's filled premium for that expiry
The denominator is the baseline's premium for both sides, so it exists even when the variant
skipped the week. The variant's own "% of premium" is reported separately, over the trades it
actually executed.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from nifty_backtest.research.stats import (
    bootstrap_mean_interval,
    lag1_autocorrelation,
    paired_t_test,
    worst_share_mean,
)

PROMISING = "promising on development"
WORSE = "worse than baseline on development"
WORSE_TAIL = "higher mean but worse drawdown or tail: not promising"
INCONCLUSIVE = "inconclusive on development"
CONSISTENT = "consistent in historical validation (previously observed)"
INCONSISTENT = "inconsistent in historical validation (previously observed)"


def _expiry_dates(trades: pd.DataFrame) -> list[date]:
    return [date.fromisoformat(str(e)[:10]) for e in trades["expiry"]]


@dataclass(frozen=True)
class Pairing:
    expiries: list[date]  # the baseline's traded expiries: the pairs
    d_pts: list[float]
    d_pct: list[float]  # % of the baseline premium
    variant_common: list[float]  # the variant's result, % of the baseline premium (0 if skipped)
    baseline_common: list[float]  # the baseline's own net % of premium
    executed: int  # variant trades on paired expiries
    extra_variant_trades: int  # variant trades on expiries the baseline did not trade


def pair(baseline: pd.DataFrame, variant: pd.DataFrame) -> Pairing:
    """Line up a variant's trades with the baseline's, expiry by expiry. A period with no
    trades is an empty table (possibly without columns): it simply has no pairs."""
    if baseline.empty:
        extra = 0 if variant.empty else len(variant)
        return Pairing([], [], [], [], [], 0, extra)
    base = dict(
        zip(
            _expiry_dates(baseline),
            zip(
                baseline["pnl_points_net"].tolist(),
                baseline["premium_fill_points"].tolist(),
                strict=True,
            ),
            strict=True,
        )
    )
    var = (
        dict(zip(_expiry_dates(variant), variant["pnl_points_net"].tolist(), strict=True))
        if not variant.empty
        else {}
    )
    expiries = sorted(base)
    d_pts, d_pct, var_common, base_common = [], [], [], []
    for e in expiries:
        base_pts, premium = base[e]
        var_pts = var.get(e, 0.0)
        d_pts.append(var_pts - base_pts)
        d_pct.append(100 * (var_pts - base_pts) / premium)
        var_common.append(100 * var_pts / premium)
        base_common.append(100 * base_pts / premium)
    return Pairing(
        expiries=expiries,
        d_pts=d_pts,
        d_pct=d_pct,
        variant_common=var_common,
        baseline_common=base_common,
        executed=sum(1 for e in expiries if e in var),
        extra_variant_trades=sum(1 for e in var if e not in base),
    )


def envelope(
    a: tuple[float, float] | None, b: tuple[float, float] | None
) -> tuple[float, float] | None:
    """The conservative envelope of two intervals: the LOWER of the two lower bounds and the
    HIGHER of the two upper bounds. It contains both intervals even when neither contains
    the other (it is not "pick the wider one"). None if either interval is missing."""
    if a is None or b is None:
        return None
    return (min(a[0], b[0]), max(a[1], b[1]))


def describe(values: list[float], seed: int, resamples: int, block: int) -> dict[str, Any]:
    """Mean, paired t-test, both bootstrap intervals and serial dependence of one series."""
    test = paired_t_test(values)
    iid = bootstrap_mean_interval(values, resamples, seed)
    blocks = bootstrap_mean_interval(values, resamples, seed, block=block)
    return {
        "n": test.n,
        "mean": test.mean,
        "t": test.t,
        "p": test.p,
        "ci_iid": iid,
        "ci_block": blocks,
        "ci_conservative": envelope(iid, blocks),
        "lag1_autocorrelation": lag1_autocorrelation(values),
    }


def compare(pairing: Pairing, seed: int, resamples: int, block: int) -> dict[str, Any]:
    """All paired statistics of one variant against the baseline in one period."""
    result = describe(pairing.d_pct, seed, resamples, block)
    result.update(
        {
            "mean_d_pts": sum(pairing.d_pts) / len(pairing.d_pts) if pairing.d_pts else math.nan,
            "executed": pairing.executed,
            "scheduled": len(pairing.expiries),
            "share_traded": pairing.executed / len(pairing.expiries) if pairing.expiries else None,
            "extra_variant_trades": pairing.extra_variant_trades,
            "tail5_variant": worst_share_mean(pairing.variant_common),
            "tail5_baseline": worst_share_mean(pairing.baseline_common),
            "worst_variant": min(pairing.variant_common) if pairing.variant_common else None,
            "worst_baseline": min(pairing.baseline_common) if pairing.baseline_common else None,
        }
    )
    return result


def development_verdict(
    adjusted_p: float | None,
    mean_d_pct: float,
    max_dd_variant: float,
    max_dd_baseline: float,
    tail_variant: float | None,
    tail_baseline: float | None,
    alpha: float,
) -> str:
    """Pre-registration 7, development."""
    if adjusted_p is None or adjusted_p >= alpha or math.isnan(mean_d_pct):
        return INCONCLUSIVE
    if mean_d_pct < 0:
        return WORSE
    tail_ok = (
        tail_variant is not None and tail_baseline is not None and tail_variant >= tail_baseline
    )
    if max_dd_variant <= max_dd_baseline and tail_ok:
        return PROMISING
    return WORSE_TAIL


def validation_verdict(mean_d_pct: float, conservative: tuple[float, float] | None) -> str:
    """Pre-registration 7, historical validation (only for variants promising on development)."""
    if conservative is not None and mean_d_pct > 0 and conservative[0] > 0:
        return CONSISTENT
    return INCONSISTENT


def final_status(development: str, validation: str | None) -> str:
    if development == PROMISING:
        if validation == CONSISTENT:
            return "awaiting forward holdout (promising on development, consistent in validation)"
        return "not supported (promising on development, inconsistent in validation)"
    if development == INCONCLUSIVE:
        return "inconclusive"
    if development == WORSE:
        return "worse than baseline"
    return "not promising (worse drawdown or tail)"


def edge_verdict(
    development: tuple[float, float] | None, validation: tuple[float, float] | None
) -> str:
    """Pre-registration 6.4: does the baseline itself earn a positive edge?"""
    if development and validation and development[0] > 0 and validation[0] > 0:
        return "positive in both previously observed periods (awaiting forward holdout)"
    return "edge not demonstrated"
