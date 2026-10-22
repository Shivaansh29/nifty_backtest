"""POST /api/runs: run a backtest with the given parameters and save it like the CLI does.

The steps are exactly those of `nifty-backtest backtest`: resolve the end date, run the
engine, save the run folder (config, manifest with git state and data hashes, logs), then
compute metrics if there was at least one trade. Nothing about the trading or the metrics
differs between a run launched here and one launched from the command line.

One launch at a time: a backtest reads the whole data store and takes a while, and two runs
saved in the same second would get the same run id.
"""

import threading
from dataclasses import replace

from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.schemas import RunRequest, RunSummary
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.api.store import RunStore
from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig, run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.indices import index_path
from nifty_backtest.metrics.summary import write_metrics
from nifty_backtest.strategies.short_straddle import ShortStraddle


def missing_inputs(data: DataConfig, costs: CostConfig) -> str | None:
    """What local input a run would need but cannot find, or None if everything is there."""
    if not any(data.processed_dir.glob("*/*.parquet")):
        return (
            f"no stored option data in {data.processed_dir}; run `nifty-backtest download` "
            "and `nifty-backtest build` first"
        )
    if not index_path(data).is_file():
        return f"no index data at {index_path(data)}; run `nifty-backtest download-index` first"
    if not costs.rates_path.is_file():
        return f"no cost-rate table at {costs.rates_path}"
    if not data.reference_dir.is_dir():
        return f"no reference folder at {data.reference_dir}"
    return None


def launch(
    request: RunRequest, settings: ApiSettings, store: RunStore, lock: threading.Lock
) -> RunSummary:
    if not lock.acquire(blocking=False):
        raise ApiError(409, "run_in_progress", "another run is being launched; try again later")
    try:
        # Resolve "up to today" before running, so the run and its saved config agree (D6).
        data = replace(
            settings.data,
            start=request.start or settings.data.start,
            end=request.end or settings.data.end_date(settings.today()),
        )
        if data.end is not None and data.start > data.end:
            raise ApiError(422, "invalid_request", f"start {data.start} is after end {data.end}")
        problem = missing_inputs(data, settings.costs)
        if problem:
            raise ApiError(503, "data_unavailable", problem)
        run_cfg = RunConfig(
            data=data,
            costs=replace(
                settings.costs,
                brokerage_per_order_rs=request.brokerage_per_order_rs,
                slippage_points_per_leg=request.slippage_points_per_leg,
            ),
            capital_rs=request.capital_rs,
        )
        strategy = ShortStraddle(
            entry_days_before_expiry=request.entry_days_before_expiry, lots=request.lots
        )
        try:
            result = run_backtest(run_cfg, strategy)
            folder = save_run(result, run_cfg, strategy, settings.runs_dir, settings.today())
        except FileExistsError as exc:
            raise ApiError(409, "run_exists", f"a run with this id already exists: {exc}") from exc
        except Exception as exc:  # report any engine failure as an API error, with its cause
            raise ApiError(500, "run_failed", f"{type(exc).__name__}: {exc}") from exc
        if not result.trades.empty:
            try:
                write_metrics(folder)
            except Exception as exc:
                raise ApiError(
                    500,
                    "run_failed",
                    f"run saved, but computing metrics failed: {type(exc).__name__}: {exc}",
                    folder.name,
                ) from exc
        return store.summary(folder.name)
    finally:
        lock.release()
