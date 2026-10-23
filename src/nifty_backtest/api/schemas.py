"""Typed request and response bodies for the REST API (Pydantic models).

Field names are the saved files' own column and key names, unchanged, so a number in the API
can be traced straight back to the file it came from.

Two kinds of model:
- ARTIFACT models describe a file a run saved (trades.csv, metrics.json, ...). They forbid
  unknown fields, so a file whose layout differs from what this code expects is reported as
  invalid instead of being served half-understood.
- API models (RunSummary, RunDetail, ErrorBody, RunRequest) are the API's own shapes.

Fields added by the M4 missing-data correction (totals_note, max_drawdown_lower_bound,
max_drawdown_note, the tables' note column) are optional: metrics written before that
correction do not have them, and the API then leaves them out of the response rather than
inventing a value. Re-running `nifty-backtest metrics <run>` adds them.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig
from nifty_backtest.strategies.short_straddle import ShortStraddle


class Artifact(BaseModel):
    # Infinity has no JSON form, and a NaN in a file must have been read as a missing value
    # (None) already, so either one here means the file is not what it should be.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


# --- run folder: config.json and manifest.json -------------------------------------------


class DataSettings(BaseModel):
    """The data window and paths a run used. Other DataConfig settings (download politeness
    and so on) are passed through as they were saved."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    data_dir: str
    reference_dir: str
    start: date
    end: date | None  # None only in runs saved before M4 stored the resolved end date


class CostSettings(Artifact):
    brokerage_per_order_rs: float
    slippage_points_per_leg: float
    rates_path: str


class RunSettings(Artifact):
    data: DataSettings
    costs: CostSettings
    capital_rs: float
    underlying: str


class StrategySettings(BaseModel):
    """Every strategy has a name, entry timing and lot count; its other parameters pass
    through as saved, so new strategies need no change here."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)
    name: str
    entry_days_before_expiry: int
    lots: int


class RunConfigFile(Artifact):
    run: RunSettings
    strategy: StrategySettings


class GitState(Artifact):
    commit: str
    uncommitted_changes: bool


class DataManifest(Artifact):
    first_trading_day: date | None
    last_trading_day: date | None
    trading_day_count: int
    option_files: int
    option_data_sha256: str
    index_data_sha256: str
    reference_files_sha256: dict[str, str]


class ManifestFile(Artifact):
    run_id: str
    git: GitState
    data: DataManifest


# --- logs: trades.csv, marks.csv, equity.csv, skipped.csv ---------------------------------


class TradeRecord(Artifact):
    """One row of trades.csv (M3 trade log, with context columns)."""

    trade_id: str
    underlying: str
    strategy: str
    entry_date: date
    expiry: date
    expiry_weekday: str
    stated_expiry_on_entry: date
    relabelled: bool
    calendar_days_to_expiry: int
    trading_days_held: int
    strike: float
    nifty_close_at_entry: float
    vix_at_entry: float | None
    ce_entry_close: float
    pe_entry_close: float
    premium_close_points: float
    premium_fill_points: float
    lot_size: int
    lot_size_source: str
    lots: int
    quantity: int
    settlement_level: float
    nifty_move_pct: float
    ce_value_at_expiry: float
    pe_value_at_expiry: float
    value_at_expiry_points: float
    pnl_points_gross: float
    pnl_points_net: float
    pnl_pct_premium_gross: float
    pnl_pct_premium_net: float
    pnl_rs_gross: float
    slippage_rs: float
    charges_rs: float
    brokerage_rs: float
    stt_rs: float
    exchange_rs: float
    ipft_rs: float
    sebi_rs: float
    stamp_rs: float
    gst_rs: float
    pnl_rs_net: float
    stale_marks: int
    missing_marks: int
    event_in_window: bool
    events: str | None


class MarkRow(Artifact):
    """One trade on one day (marks.csv). Values are None where a mark is missing."""

    trade_id: str
    expiry: date
    date: date
    ce_mark: float | None
    pe_mark: float | None
    position_value_points: float | None
    mtm_points_gross: float | None
    mtm_rs_net: float | None
    stale_mark: bool
    missing_mark: bool


class EquityPoint(Artifact):
    """Account value at one close (equity.csv). A run with no trades saves only date and
    equity, so the other two columns are optional."""

    date: date
    realised_rs: float | None = None
    open_mtm_rs: float | None = None
    equity_rs: float | None


class SkippedWeek(Artifact):
    expiry: date
    entry_date: date | None
    reason: str


class TradeDetail(BaseModel):
    """A single trade with its daily marks (drill-down)."""

    trade: TradeRecord
    marks: list[MarkRow]


# --- metrics: metrics.json, yearly.csv, monthly.csv ---------------------------------------


class Ratio(Artifact):
    value: float | None
    note: str


class SeriesMetrics(Artifact):
    first_day: date
    last_day: date
    final_equity_rs: float | None
    total_pnl_rs: float | None
    roi: float | None
    cagr: float | None
    totals_note: str | None = None
    max_drawdown_rs: float
    max_drawdown_rs_peak: date | None
    max_drawdown_rs_trough: date | None
    max_drawdown_rs_recovered: date | None
    max_drawdown_pct: float
    max_drawdown_pct_peak: date | None
    max_drawdown_pct_trough: date | None
    max_drawdown_pct_recovered: date | None
    max_drawdown_lower_bound: bool | None = None
    max_drawdown_note: str | None = None
    missing_days: int
    sharpe_rupee: Ratio
    sortino_rupee: Ratio


class StrategyMetrics(SeriesMetrics):
    sharpe_notional: Ratio
    sortino_notional: Ratio
    sensitivity_sharpe_notional_at_rf: Ratio
    sensitivity_sortino_notional_at_rf: Ratio
    notional_missing_days: int


class BenchmarkMetrics(SeriesMetrics):
    tri_start: float
    tri_end: float
    index_data_matches_run: bool


class BenchmarkNotComputed(Artifact):
    not_computed: str


class BestWorst(Artifact):
    best: float
    best_trade: str
    worst: float
    worst_trade: str


class TradeStats(Artifact):
    trades: int
    wins: int
    losses: int
    zero_pnl: int
    win_rate: float
    avg_win_rs: float | None
    avg_loss_rs: float | None
    avg_win_points: float | None
    avg_loss_points: float | None
    avg_win_pct_premium: float | None
    avg_loss_pct_premium: float | None
    rs: BestWorst
    points: BestWorst
    mean_pct_premium_net: float
    mean_points_net: float
    t_stat_pct_premium_net: float | None
    t_stat_points_net: float | None
    gross_rs: float
    slippage_rs: float
    charges_rs: float
    net_rs: float
    charges_by_line_rs: dict[str, float]


class Reconciliation(Artifact):
    """Each check should be ~0; None means it needed a missing value and was not possible."""

    gross_minus_slippage_minus_charges_minus_net: float | None
    final_equity_minus_capital_minus_trade_net: float | None
    yearly_net_by_expiry_minus_total: float | None
    yearly_pnl_by_date_minus_total: float | None
    monthly_pnl_minus_total: float | None
    notional_daily_sum_minus_trade_sum: float | None


class MetricsSettings(Artifact):
    risk_free_rate: float
    notional_target_rate: float
    periods_per_year: int


class Metrics(Artifact):
    """metrics.json (M4)."""

    run_id: str
    git: GitState
    metrics_config: MetricsSettings
    capital_rs: float
    strategy_net: StrategyMetrics
    strategy_gross: StrategyMetrics
    benchmark_nifty50_tri: BenchmarkMetrics | BenchmarkNotComputed
    trades: TradeStats
    reconciliation: Reconciliation


class PeriodRow(Artifact):
    """Shared columns of yearly.csv and monthly.csv. `return` is a Python keyword, so the
    attribute is `return_`; in JSON it is still called "return"."""

    trading_days: int
    start_equity_rs: float | None
    end_equity_rs: float | None
    pnl_rs: float | None
    return_: float | None = Field(alias="return")
    benchmark_return: float | None = None  # absent when the benchmark was not computed
    note: str | None = None


class MonthRow(PeriodRow):
    month: str


class DailyPoint(Artifact):
    """One day of daily.csv (M6): the series behind the dashboard charts, computed by the
    metrics code (never by the API or the browser). Drawdowns are positive fractions or
    rupees below the running peak; benchmark columns are None if the TRI was unavailable."""

    date: date
    equity_net_rs: float | None
    equity_gross_rs: float | None
    drawdown_net_rs: float | None
    drawdown_net_pct: float | None
    benchmark_equity_rs: float | None
    benchmark_drawdown_pct: float | None


class YearRow(PeriodRow):
    year: int
    partial_year: bool
    trades: int
    win_rate: float | None
    net_rs_by_expiry: float
    net_points_by_expiry: float
    mean_pct_premium_net: float | None
    t_stat_pct_premium_net: float | None
    t_stat_points_net: float | None
    max_drawdown_rs: float
    max_drawdown_pct: float
    max_drawdown_lower_bound: bool | None = None
    sharpe_notional: float | None
    sortino_notional: float | None
    sharpe_rupee: float | None


# --- the API's own shapes ------------------------------------------------------------------

RunStatus = Literal["complete", "metrics_missing", "invalid"]


class Headline(BaseModel):
    """A few numbers from metrics.json for the run list (net of costs)."""

    total_pnl_rs: float | None
    roi: float | None
    cagr: float | None
    max_drawdown_pct: float
    sharpe_notional: float | None
    sortino_notional: float | None
    trades: int
    win_rate: float


class RunSummary(BaseModel):
    run_id: str
    created_at: datetime  # from the run id (local time when the run was saved)
    status: RunStatus
    problems: list[str]  # why the run is invalid or incomplete; empty when complete
    strategy: str | None
    git_commit: str | None
    uncommitted_changes: bool | None
    first_trading_day: date | None
    last_trading_day: date | None
    headline: Headline | None  # None unless metrics are present and valid


class RunDetail(RunSummary):
    config: RunConfigFile
    manifest: ManifestFile
    artifacts: dict[str, bool]  # file name -> present in the run folder
    trade_count: int | None  # None if trades.csv cannot be read (see problems)
    skipped_count: int | None


class ErrorBody(BaseModel):
    """Every error response has this shape."""

    error: str  # machine-readable code, e.g. run_not_found
    detail: str  # human-readable explanation
    run_id: str | None = None
    artifact: str | None = None


# Defaults come from the strategy and cost classes themselves, so the API and the CLI start
# from the same values without repeating the numbers here.
_STRATEGY = ShortStraddle()
_COSTS = CostConfig()
_RUN = RunConfig()


class RunRequest(BaseModel):
    """Parameters for POST /api/runs: the same choices `nifty-backtest backtest` offers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    start: date | None = Field(
        default=None, description="first day; default: the data config's start"
    )
    end: date | None = Field(default=None, description="last day; default: today")
    entry_days_before_expiry: int = Field(default=_STRATEGY.entry_days_before_expiry, ge=1)
    lots: int = Field(default=_STRATEGY.lots, ge=1)
    brokerage_per_order_rs: float = Field(default=_COSTS.brokerage_per_order_rs, ge=0)
    slippage_points_per_leg: float = Field(default=_COSTS.slippage_points_per_leg, ge=0)
    capital_rs: float = Field(default=_RUN.capital_rs, gt=0)

    @model_validator(mode="after")
    def _start_not_after_end(self) -> "RunRequest":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("start must not be after end")
        return self


class Health(BaseModel):
    status: Literal["ok"]
    version: str
