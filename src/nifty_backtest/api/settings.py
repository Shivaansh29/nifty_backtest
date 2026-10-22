"""Where the API finds runs and market data. Paths are relative to the working directory,
like the CLI's, so `nifty-backtest serve` run from the repository sees the same runs/ and
data/ as `nifty-backtest backtest`."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.marketdata.config import DataConfig


@dataclass(frozen=True)
class ApiSettings:
    runs_dir: Path = Path("runs")
    # Used only by POST /api/runs: the data a launched run reads, and the dated cost-rate
    # table. Brokerage and slippage come from each request instead.
    data: DataConfig = field(default_factory=DataConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    # "Today", for a launch whose end date is left open (tests pass a fixed date).
    today: Callable[[], date] = date.today
