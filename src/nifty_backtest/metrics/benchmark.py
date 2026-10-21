"""Buy-and-hold NIFTY 50 TRI over exactly the run's dates (spec §6).

The starting capital buys the TRI at the close of the run's first trading day and holds it to
the last, so the strategy and the benchmark cover the same days. TRI (total return index)
assumes dividends are reinvested. No trading costs or taxes are charged to the benchmark.

Coverage rules: the TRI value must exist on the first and last day, or the benchmark is not
computed. A missing TRI value on any day in between is left missing (never interpolated), so
the daily ratios become None while the start-to-end figures still hold.
"""

from datetime import date

import pandas as pd


class BenchmarkError(ValueError):
    pass


def tri_equity(tri: pd.Series, days: list[date], capital: float) -> pd.Series:
    """Rupee value of `capital` invested in the TRI at the first day's close."""
    aligned = tri.reindex(days)
    if pd.isna(aligned.iloc[0]) or pd.isna(aligned.iloc[-1]):
        raise BenchmarkError("NIFTY 50 TRI is missing on the first or last day of the run")
    return (capital * aligned / float(aligned.iloc[0])).rename("benchmark_tri")
