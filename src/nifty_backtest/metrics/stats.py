"""Pure metric formulas (spec §6). No file access here: every function takes plain series.

Conventions (approved for M4):
- Daily returns are simple returns. A return series may contain NaN where a day's value is
  missing; it is never "stitched" over the gap.
- Sharpe = mean(r - target) / sd(r - target) x sqrt(periods), sample sd (ddof = 1).
- Sortino = mean(r - target) / DD x sqrt(periods), DD = sqrt(mean(min(r - target, 0)^2)) over
  ALL days, so days above target count as zero downside.
- A daily target rate comes from an annual one geometrically: (1 + annual)^(1/periods) - 1.
- If a ratio cannot be computed honestly (a gap in the series, too few days, zero spread, no
  day below target) it is reported as None with the reason, never as 0 or infinity.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Ratio:
    value: float | None
    note: str = ""


def daily_rate(annual: float, periods: int) -> float:
    return float((1 + annual) ** (1 / periods) - 1)


def _usable(returns: pd.Series) -> str:
    """'' if the series can feed a daily ratio, else the reason it cannot."""
    gaps = int(returns.isna().sum())
    if gaps:
        return f"{gaps} daily values missing: a multi-day return would be needed, so not computed"
    if len(returns) < 2:
        return "fewer than 2 daily returns"
    return ""


def sharpe(returns: pd.Series, target_daily: float, periods: int) -> Ratio:
    reason = _usable(returns)
    if reason:
        return Ratio(None, reason)
    excess = returns - target_daily
    spread = float(excess.std(ddof=1))
    if spread == 0:
        return Ratio(None, "returns never vary (zero standard deviation)")
    return Ratio(float(excess.mean()) / spread * math.sqrt(periods))


def sortino(returns: pd.Series, target_daily: float, periods: int) -> Ratio:
    reason = _usable(returns)
    if reason:
        return Ratio(None, reason)
    excess = returns - target_daily
    downside = math.sqrt(float((excess.clip(upper=0) ** 2).mean()))
    if downside == 0:
        return Ratio(None, "no daily return below the target (zero downside deviation)")
    return Ratio(float(excess.mean()) / downside * math.sqrt(periods))


def roi(final_value: float, capital: float) -> float:
    return (final_value - capital) / capital


def cagr(start_value: float, end_value: float, start: date, end: date) -> float | None:
    """Annualised growth over the calendar time between two dates (365.25-day years)."""
    days = (end - start).days
    if days <= 0 or start_value <= 0 or end_value <= 0:
        return None
    return float((end_value / start_value) ** (365.25 / days) - 1)


@dataclass(frozen=True)
class Drawdown:
    max_rs: float
    max_pct: float
    rs_peak_date: date | None
    rs_trough_date: date | None
    rs_recovery_date: date | None  # None: not yet recovered (or no drawdown)
    pct_peak_date: date | None
    pct_trough_date: date | None
    pct_recovery_date: date | None
    missing_days: int  # days skipped because their value is missing


def max_drawdown(equity: pd.Series, start_value: float) -> Drawdown:
    """Largest fall from a running peak, in rupees and in % of that peak.

    The running peak starts at `start_value` (the capital), so a loss from day one counts.
    Days with a missing value are skipped and counted: a trough could hide in a gap.
    """
    values = equity.dropna()
    missing = len(equity) - len(values)
    days: list[date] = list(values.index)
    peak_value: float = start_value
    peak_date: date | None = None
    best_rs: tuple[float, date | None, date | None] = (0.0, None, None)
    best_pct: tuple[float, date | None, date | None] = (0.0, None, None)
    for day, value in zip(days, values.tolist(), strict=True):
        if value > peak_value:
            peak_value, peak_date = float(value), day
        fall = peak_value - float(value)
        if fall > best_rs[0]:
            best_rs = (fall, peak_date, day)
        if peak_value > 0 and fall / peak_value > best_pct[0]:
            best_pct = (fall / peak_value, peak_date, day)

    def recovery(peak: date | None, trough: date | None) -> date | None:
        if trough is None:
            return None
        level = start_value if peak is None else float(values[peak])
        for day, value in zip(days, values.tolist(), strict=True):
            if day > trough and value >= level:
                return day
        return None

    return Drawdown(
        max_rs=best_rs[0],
        max_pct=best_pct[0],
        rs_peak_date=best_rs[1],
        rs_trough_date=best_rs[2],
        rs_recovery_date=recovery(best_rs[1], best_rs[2]),
        pct_peak_date=best_pct[1],
        pct_trough_date=best_pct[2],
        pct_recovery_date=recovery(best_pct[1], best_pct[2]),
        missing_days=missing,
    )


def t_stat(values: Sequence[float]) -> float | None:
    """t = mean / (s / sqrt(n)), s the sample standard deviation. Tests whether the average
    trade differs from zero; assumes trades are independent (weekly, non-overlapping)."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    spread = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    if spread == 0:
        return None
    return mean / (spread / math.sqrt(n))
