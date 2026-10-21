"""Performance metrics (M4), computed from a SAVED run folder so any run can be re-analysed.

series.py     daily series: rupee equity (net / gross) and return on notional (net / gross)
stats.py      pure formulas: ROI, CAGR, drawdown, Sharpe, Sortino, t-statistic
benchmark.py  NIFTY 50 TRI buy-and-hold over the run's dates
summary.py    puts it together: metrics.json, yearly.csv, monthly.csv, summary.md, CLI text
"""
