"""Market indicators for the M7 entry filters, from the stored NIFTY / VIX daily data.

Only past information is used: a filter for an entry on day t reads the value at the close of
the previous session (t-1), never day t itself (see the M7 pre-registration, section 4).

ADX (Average Directional Index, J. Welles Wilder, 1978) measures trend STRENGTH (not
direction) on a 0-100 scale. For each day t after the first:
  TR   = max(high - low, |high - previous close|, |low - previous close|)   true range
  +DM  = high - previous high, if that is larger than (previous low - low) and positive, else 0
  -DM  = previous low - low,   if that is larger than (high - previous high) and positive, else 0
Wilder smoothing over n days: the first value is the SUM of the first n values, then
  S_t = S_(t-1) - S_(t-1) / n + x_t
  +DI = 100 x smoothed +DM / smoothed TR,  -DI likewise
  DX  = 100 x |+DI - -DI| / (+DI + -DI)
ADX: the first value is the MEAN of the first n DX values, then
  ADX_t = (ADX_(t-1) x (n-1) + DX_t) / n.
So the first ADX exists on the 2n-th day of data (index 2n - 1); earlier days have none.
"""

import math
from datetime import date

import pandas as pd


def wilder_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """ADX for every day of the series (NaN until enough history exists)."""
    highs, lows, closes = high.tolist(), low.tolist(), close.tolist()
    count = len(closes)
    adx = [math.nan] * count
    if count < 2 * period:
        return pd.Series(adx, index=close.index, name="adx")
    tr, plus_dm, minus_dm = [math.nan], [math.nan], [math.nan]  # day 0 has no previous day
    for t in range(1, count):
        up = highs[t] - highs[t - 1]
        down = lows[t - 1] - lows[t]
        tr.append(
            max(highs[t] - lows[t], abs(highs[t] - closes[t - 1]), abs(lows[t] - closes[t - 1]))
        )
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)

    dx: list[float] = [math.nan] * count
    s_tr = s_plus = s_minus = 0.0
    for t in range(1, count):
        if t < period:
            s_tr, s_plus, s_minus = s_tr + tr[t], s_plus + plus_dm[t], s_minus + minus_dm[t]
            continue
        if t == period:
            s_tr, s_plus, s_minus = s_tr + tr[t], s_plus + plus_dm[t], s_minus + minus_dm[t]
        else:
            s_tr = s_tr - s_tr / period + tr[t]
            s_plus = s_plus - s_plus / period + plus_dm[t]
            s_minus = s_minus - s_minus / period + minus_dm[t]
        plus_di = 100 * s_plus / s_tr if s_tr else 0.0
        minus_di = 100 * s_minus / s_tr if s_tr else 0.0
        total = plus_di + minus_di
        dx[t] = 100 * abs(plus_di - minus_di) / total if total else 0.0

    first = 2 * period - 1  # DX exists from index `period`; n of them end here
    adx[first] = sum(dx[period : first + 1]) / period
    for t in range(first + 1, count):
        adx[t] = (adx[t - 1] * (period - 1) + dx[t]) / period
    return pd.Series(adx, index=close.index, name="adx")


def value_before(series: pd.Series, day: date) -> float:
    """The series' value on the last session strictly before `day` (t-1), or NaN if there is
    none. The series is indexed by trading date in ascending order."""
    earlier = series[series.index < day]
    return float(earlier.iloc[-1]) if len(earlier) else math.nan


def previous_session(days: list[date], day: date) -> date | None:
    """The last trading day strictly before `day`."""
    earlier = [d for d in days if d < day]
    return earlier[-1] if earlier else None
