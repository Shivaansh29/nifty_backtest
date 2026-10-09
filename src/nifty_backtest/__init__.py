"""NIFTY options backtester: backtests NIFTY index option strategies on NSE end-of-day data."""

from importlib.metadata import version

# pyproject.toml is the only place the version is written. Reading it back from the installed
# package's metadata means the two can never disagree.
__version__ = version("nifty-backtest")
