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


class EntryFilterSettings(Artifact):
    """M7 entry filter (previous-close information only)."""

    vix_min: float | None
    vix_max: float | None
    adx_max: float | None
    adx_period: int
    skip_scheduled_events: bool


class ExitRuleSettings(Artifact):
    """M7 early exits of individual legs, from their daily high/low."""

    stop_multiple: float | None
    take_profit_decay: float | None


class RunSettings(Artifact):
    data: DataSettings
    costs: CostSettings
    capital_rs: float
    underlying: str
    # M7 research conditions. Absent in runs saved before M7; null / "entry_close" = baseline.
    entry_filter: EntryFilterSettings | None = None
    exit_rule: ExitRuleSettings | None = None
    strike_reference: Literal["entry_close", "previous_close"] | None = None


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
    # Per unit. For a leg bought back early by an M7 exit rule, its buy-back price (the
    # *_exit_* columns below say which legs and when).
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
    # M7 columns, present only in runs with that research condition switched on.
    # With an exit rule: how each leg ended ("stop", "take_profit" or "expiry"), when, and at
    # what price (trigger price, or intrinsic value at expiry).
    ce_exit_date: date | None = None
    ce_exit_reason: Literal["stop", "take_profit", "expiry"] | None = None
    ce_exit_price: float | None = None
    pe_exit_date: date | None = None
    pe_exit_reason: Literal["stop", "take_profit", "expiry"] | None = None
    pe_exit_price: float | None = None
    exit_charges_rs: float | None = None
    no_info_days: int | None = None
    # With an entry filter: the previous-close information the decision used.
    info_date: date | None = None
    vix_prev_close: float | None = None
    adx_prev: float | None = None
    knowable_events: str | None = None
    # With strike_reference = previous_close: the NIFTY level that picked the strike.
    strike_reference_level: float | None = None


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
    ce_closed: bool | None = None  # M7 exit rule: leg already bought back by this close
    pe_closed: bool | None = None


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


# --- M7 studies: studies/<study_id>/study.json ---------------------------------------------
#
# A study is a pre-registered set of runs (docs/research/m7_preregistration.md). Its
# study.json holds every comparison, verdict and table, all computed in Python by
# nifty_backtest.research; the API only checks and serves it. Fields that a row only has in
# some cases (paired statistics: not on the baseline's own rows; most numbers: not on a run
# with no trades) are optional and left out of responses when the file lacks them.

Interval = tuple[float, float]


class StudyPeriod(Artifact):
    name: str
    start: date
    end: date


class ForwardHoldout(Artifact):
    first_entry: date
    min_trades: int
    latest_evaluation: date


class PlanFileCommit(Artifact):
    last_commit: str  # empty if the file was never committed


class PlanGitState(Artifact):
    head: str
    files: dict[str, PlanFileCommit]
    uncommitted_changes: bool


class StudyPlanInfo(Artifact):
    name: str
    path: str
    sha256: str
    preregistration_path: str
    preregistration_sha256: str
    git: PlanGitState
    periods: list[StudyPeriod]  # development, then validation (previously observed)
    forward_holdout: ForwardHoldout
    holm_family: list[str]
    alpha: float
    seed: int
    bootstrap_resamples: int
    block_length: int
    thresholds: dict[str, float]


class EdgePeriod(Artifact):
    """The baseline's own net % of premium in one period, with both bootstrap intervals and
    their conservative envelope (lower of the lower bounds, higher of the upper bounds)."""

    period: str
    n: int
    mean: float | None
    t: float | None
    p: float | None
    ci_iid: Interval | None
    ci_block: Interval | None
    ci_conservative: Interval | None
    lag1_autocorrelation: float | None


class StudyEdge(Artifact):
    verdict: str
    periods: list[EdgePeriod]

    @model_validator(mode="before")
    @classmethod
    def _from_file_layout(cls, raw: object) -> object:
        # study.json keys the periods by name next to the verdict:
        #   {"development": {...}, "validation": {...}, "verdict": "..."}
        # Here they become a list, so the shape does not depend on the period names. Only
        # keys move; no value changes.
        if isinstance(raw, dict) and "periods" not in raw:
            periods = [
                {"period": name, **stats} for name, stats in raw.items() if name != "verdict"
            ]
            return {"verdict": raw.get("verdict"), "periods": periods}
        return raw


class StudyVerdict(Artifact):
    development: str
    validation: str | None  # only for variants promising on development
    status: str


class StudyVariantSettings(Artifact):
    """A variant's full settings: the baseline's plus its one change (study plan)."""

    entry_days_before_expiry: int
    lots: int
    brokerage_per_order_rs: float
    slippage_points_per_leg: float
    capital_rs: float
    strike_reference: Literal["entry_close", "previous_close"]
    vix_min: float | None
    vix_max: float | None
    adx_max: float | None
    skip_scheduled_events: bool
    stop_multiple: float | None
    take_profit_decay: float | None


StudyRole = Literal["baseline", "primary", "sensitivity", "realism", "descriptive"]


class StudyRunRecord(Artifact):
    key: str  # the variant id, or e.g. B0@slip1-brk20 for a cost-grid cell
    variant: str
    role: StudyRole
    of: str | None
    period: str
    run_id: str  # a run folder in studies/<study_id>/runs/
    trades: int
    skipped: int
    settings: StudyVariantSettings


class ComparisonRow(Artifact):
    """One variant in one period: its own run's numbers (from its metrics.json) and, for
    every variant but the baseline, the paired comparison with the baseline (paired_*, in %
    of the baseline's premium for the same expiry; a skipped week counts as 0 points)."""

    variant: str
    role: StudyRole
    of: str | None
    change: str
    period: str
    run_id: str
    trades: int
    net_pnl_rs: float
    max_drawdown_pct: float
    win_rate: float | None = None
    gross_pnl_rs: float | None = None
    roi: float | None = None
    cagr: float | None = None
    max_drawdown_rs: float | None = None
    sharpe_notional: float | None = None
    sortino_notional: float | None = None
    sharpe_rupee: float | None = None
    sortino_rupee: float | None = None
    tri_roi: float | None = None
    mean_pct_premium_executed: float | None = None
    t_pct_premium_executed: float | None = None
    avg_win_rs: float | None = None
    avg_loss_rs: float | None = None
    worst_trade_rs: float | None = None
    charges_rs: float | None = None
    exit_charges_rs: float | None = None
    stop_exits: int | None = None
    take_profit_exits: int | None = None
    paired_n: int | None = None
    paired_mean: float | None = None
    paired_t: float | None = None
    paired_p: float | None = None
    paired_p_holm: float | None = None  # primaries only, development only
    paired_ci_iid: Interval | None = None
    paired_ci_block: Interval | None = None
    paired_ci_conservative: Interval | None = None
    paired_lag1_autocorrelation: float | None = None
    paired_mean_d_pts: float | None = None
    paired_executed: int | None = None
    paired_scheduled: int | None = None
    paired_share_traded: float | None = None
    paired_extra_variant_trades: int | None = None
    paired_tail5_variant: float | None = None
    paired_tail5_baseline: float | None = None
    paired_worst_variant: float | None = None
    paired_worst_baseline: float | None = None


class FamilyRow(Artifact):
    """One point of a sensitivity family. Reported in full, never used to choose a setting."""

    family: str
    setting: str
    value: int | float | str | bool | None
    variant: str
    role: StudyRole
    period: str
    mean_d_pct: float | None
    ci_conservative: Interval | None
    net_pnl_rs: float
    trades: int
    max_drawdown_pct: float
    plateau_same_sign: bool | None = None  # absent for the baseline-centred family


class CostGridRow(Artifact):
    base: str
    period: str
    slippage_points_per_leg: float
    brokerage_per_order_rs: float
    trades: int
    net_pnl_rs: float
    mean_pct_premium_net: float | None
    t_pct_premium: float | None
    sharpe_notional: float | None
    max_drawdown_pct: float
    run_id: str


class RegimeRow(Artifact):
    """The baseline in one regime group (descriptive only)."""

    period: str
    grouping: str
    group: str
    trades: int
    mean_pct_premium_net: float | None
    total_net_rs: float
    win_rate: float


class StudyFile(Artifact):
    """study.json, checked field by field."""

    study_id: str
    created_at: datetime
    plan: StudyPlanInfo
    edge: StudyEdge
    verdicts: dict[str, StudyVerdict]
    comparison: list[ComparisonRow]
    families: list[FamilyRow]
    cost_grid: list[CostGridRow]
    regimes: list[RegimeRow]
    runs: list[StudyRunRecord]


StudyStatus = Literal["complete", "invalid"]


class StudySummary(BaseModel):
    study_id: str
    status: StudyStatus
    problems: list[str]  # why the study is invalid; empty when complete
    name: str | None
    created_at: datetime | None
    git_head: str | None
    periods: list[StudyPeriod]
    edge_verdict: str | None
    statuses: dict[str, str]  # primary variant -> final status
    run_count: int | None
