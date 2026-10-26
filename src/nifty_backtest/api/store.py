"""Find saved runs and read their files, checking each one (M5).

The API only READS run folders. It never recomputes or rewrites a saved result, so every
number it serves is the number on disk (`nifty-backtest metrics <run>` is how metrics are
(re)computed).

A run folder is runs/<run_id>/, where run_id looks like 20261022-191259-short_straddle.
Its files fall into two groups:
  core     config.json, manifest.json, trades.csv, marks.csv, equity.csv, skipped.csv
           (written by `save_run`; all required)
  metrics  metrics.json, yearly.csv, monthly.csv (written by `write_metrics`; all three or
           none: none means metrics were never computed, which is a normal state)
  daily    daily.csv (written by `write_metrics` from M6 on; optional, older runs lack it)

Every file is parsed into its Pydantic model before it is served. A file that is missing,
unreadable or shaped differently from what the code expects raises an ApiError naming the
file and the problem; nothing is served half-read.
"""

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
from pydantic import BaseModel, TypeAdapter, ValidationError

from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.schemas import (
    DailyPoint,
    EquityPoint,
    Headline,
    ManifestFile,
    MarkRow,
    Metrics,
    MonthRow,
    RunConfigFile,
    RunDetail,
    RunStatus,
    RunSummary,
    SkippedWeek,
    StrategyMetrics,
    TradeDetail,
    TradeRecord,
    YearRow,
)

# Same shape as `save_run` creates: timestamp, then the strategy name. Checking it before any
# path is built also rules out "..", slashes and other ways of escaping the runs folder.
RUN_ID = re.compile(r"^\d{8}-\d{6}-[a-z0-9_]+$")
CORE_FILES = (
    "config.json",
    "manifest.json",
    "trades.csv",
    "marks.csv",
    "equity.csv",
    "skipped.csv",
)
METRICS_FILES = ("metrics.json", "yearly.csv", "monthly.csv")
# Added in M6. Metrics written earlier lack it, so it is optional: its absence does not make a
# run incomplete, but /daily then says how to add it.
DAILY_FILE = "daily.csv"
# A run with no trades saves trades.csv and marks.csv with no columns at all (an empty
# DataFrame); for these two files, "no columns" means "no rows", not a broken file.
MAY_BE_EMPTY = ("trades.csv", "marks.csv")

Model = TypeVar("Model", bound=BaseModel)


def created_at(run_id: str) -> datetime:
    return datetime.strptime(run_id[:15], "%Y%m%d-%H%M%S")


class RunStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    # --- locating runs ---------------------------------------------------------------

    def run_ids(self) -> list[str]:
        """Every run folder, newest first. Anything else in runs/ is ignored."""
        if not self.runs_dir.is_dir():
            return []
        ids = [p.name for p in self.runs_dir.iterdir() if p.is_dir() and RUN_ID.match(p.name)]
        return sorted(ids, reverse=True)

    def folder(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id):
            raise ApiError(422, "invalid_request", f"not a run id: {run_id!r}")
        path = self.runs_dir / run_id
        if not path.is_dir():
            raise ApiError(404, "run_not_found", f"no run {run_id} in {self.runs_dir}", run_id)
        return path

    # --- reading and checking one file -------------------------------------------------

    def _path(self, run_id: str, name: str) -> Path:
        path = self.folder(run_id) / name
        if not path.is_file():
            raise ApiError(500, "artifact_invalid", f"{name} is missing", run_id, name)
        return path

    def _json(self, run_id: str, name: str, model: type[Model]) -> Model:
        path = self._path(run_id, name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
            return model.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise ApiError(500, "artifact_invalid", explain(name, exc), run_id, name) from exc

    def _csv(self, run_id: str, name: str, model: type[Model]) -> list[Model]:
        path = self._path(run_id, name)
        try:
            frame = pd.read_csv(path)
        except pd.errors.EmptyDataError as exc:
            if name in MAY_BE_EMPTY:
                return []
            raise ApiError(500, "artifact_invalid", f"{name} is empty", run_id, name) from exc
        except (ValueError, pd.errors.ParserError) as exc:
            raise ApiError(500, "artifact_invalid", explain(name, exc), run_id, name) from exc
        # Empty cells are read as NaN; in the API they are null.
        records = frame.astype(object).where(frame.notna(), None).to_dict("records")
        try:
            return TypeAdapter(list[model]).validate_python(records)  # type: ignore[valid-type]
        except ValidationError as exc:
            raise ApiError(500, "artifact_invalid", explain(name, exc), run_id, name) from exc

    # --- the run's files ---------------------------------------------------------------

    def config(self, run_id: str) -> RunConfigFile:
        return self._json(run_id, "config.json", RunConfigFile)

    def manifest(self, run_id: str) -> ManifestFile:
        manifest = self._json(run_id, "manifest.json", ManifestFile)
        if manifest.run_id != run_id:
            raise ApiError(
                500,
                "artifact_invalid",
                f"manifest.json belongs to run {manifest.run_id}, not to this folder",
                run_id,
                "manifest.json",
            )
        return manifest

    def trades(self, run_id: str) -> list[TradeRecord]:
        self.manifest(run_id)  # a folder whose manifest is wrong is not served at all
        return self._csv(run_id, "trades.csv", TradeRecord)

    def trade(self, run_id: str, trade_id: str) -> TradeDetail:
        matches = [t for t in self.trades(run_id) if t.trade_id == trade_id]
        if not matches:
            raise ApiError(404, "trade_not_found", f"run {run_id} has no trade {trade_id}", run_id)
        marks = [m for m in self._csv(run_id, "marks.csv", MarkRow) if m.trade_id == trade_id]
        return TradeDetail(trade=matches[0], marks=sorted(marks, key=lambda m: m.date))

    def equity(self, run_id: str) -> list[EquityPoint]:
        self.manifest(run_id)
        return self._csv(run_id, "equity.csv", EquityPoint)

    def skipped(self, run_id: str) -> list[SkippedWeek]:
        self.manifest(run_id)
        return self._csv(run_id, "skipped.csv", SkippedWeek)

    def _require_metrics(self, run_id: str) -> None:
        folder = self.folder(run_id)
        present = [name for name in METRICS_FILES if (folder / name).is_file()]
        if not present:
            raise ApiError(
                409,
                "metrics_not_computed",
                f"metrics have not been computed for this run; run "
                f"`nifty-backtest metrics {self.runs_dir / run_id}`",
                run_id,
            )
        missing = [name for name in METRICS_FILES if name not in present]
        if missing:
            raise ApiError(
                500,
                "artifact_invalid",
                f"metrics files incomplete: {', '.join(missing)} missing",
                run_id,
                missing[0],
            )

    def metrics(self, run_id: str) -> Metrics:
        self._require_metrics(run_id)
        metrics = self._json(run_id, "metrics.json", Metrics)
        # Stale or copied metrics: they must describe THIS run's trade log.
        trade_rows = len(self.trades(run_id))
        if metrics.run_id != run_id or metrics.trades.trades != trade_rows:
            raise ApiError(
                500,
                "artifact_invalid",
                f"metrics.json does not match this run (run {metrics.run_id}, "
                f"{metrics.trades.trades} trades; the trade log has {trade_rows})",
                run_id,
                "metrics.json",
            )
        return metrics

    def yearly(self, run_id: str) -> list[YearRow]:
        self.metrics(run_id)  # the tables are only as valid as the metrics they belong to
        return self._csv(run_id, "yearly.csv", YearRow)

    def monthly(self, run_id: str) -> list[MonthRow]:
        self.metrics(run_id)
        return self._csv(run_id, "monthly.csv", MonthRow)

    def daily(self, run_id: str) -> list[DailyPoint]:
        self.metrics(run_id)
        if not (self.folder(run_id) / DAILY_FILE).is_file():
            raise ApiError(
                409,
                "metrics_not_computed",
                "this run's metrics were computed before daily series were saved (M6); run "
                f"`nifty-backtest metrics {self.runs_dir / run_id}` to add daily.csv",
                run_id,
                DAILY_FILE,
            )
        return self._csv(run_id, DAILY_FILE, DailyPoint)

    # --- summaries -----------------------------------------------------------------------

    def summary(self, run_id: str) -> RunSummary:
        """Status of one run, checking every file. Never raises for a broken run: the
        problems are listed instead, so one bad folder cannot break the run list."""
        self.folder(run_id)
        problems: list[str] = []

        def attempt(read: Callable[[], Any]) -> Any:
            try:
                return read()
            except ApiError as exc:
                if exc.detail not in problems:
                    problems.append(exc.detail)
                return None

        config: RunConfigFile | None = attempt(lambda: self.config(run_id))
        manifest: ManifestFile | None = attempt(lambda: self.manifest(run_id))
        for read in (self.trades, self.equity, self.skipped):
            attempt(lambda read=read: read(run_id))  # type: ignore[misc]
        attempt(lambda: self._csv(run_id, "marks.csv", MarkRow))
        status: RunStatus = "invalid" if problems else "complete"
        metrics: Metrics | None = None
        try:
            self._require_metrics(run_id)
        except ApiError as exc:
            # 409: never computed (a normal state). Anything else: metrics files incomplete.
            if exc.status != 409:
                status = "invalid"
            elif not problems:
                status = "metrics_missing"
            problems.append(exc.detail)
        else:
            metrics = attempt(lambda: self.metrics(run_id))
            attempt(lambda: self._csv(run_id, "yearly.csv", YearRow))
            attempt(lambda: self._csv(run_id, "monthly.csv", MonthRow))
            if (self.folder(run_id) / DAILY_FILE).is_file():
                attempt(lambda: self._csv(run_id, DAILY_FILE, DailyPoint))
            if problems:
                status, metrics = "invalid", None
        return RunSummary(
            run_id=run_id,
            created_at=created_at(run_id),
            status=status,
            problems=problems,
            strategy=config.strategy.name if config else None,
            git_commit=manifest.git.commit if manifest else None,
            uncommitted_changes=manifest.git.uncommitted_changes if manifest else None,
            first_trading_day=manifest.data.first_trading_day if manifest else None,
            last_trading_day=manifest.data.last_trading_day if manifest else None,
            headline=_headline(metrics) if metrics else None,
        )

    def list_runs(self) -> list[RunSummary]:
        return [self.summary(run_id) for run_id in self.run_ids()]

    def detail(self, run_id: str) -> RunDetail:
        summary = self.summary(run_id)
        folder = self.folder(run_id)
        # Config and manifest are what describe a run; without them there is no detail.
        config, manifest = self.config(run_id), self.manifest(run_id)

        def count(read: Callable[[str], list[Any]]) -> int | None:
            try:
                return len(read(run_id))
            except ApiError:
                return None  # the file itself is broken; `problems` says why

        return RunDetail(
            **summary.model_dump(),
            config=config,
            manifest=manifest,
            artifacts={
                name: (folder / name).is_file()
                for name in (*CORE_FILES, *METRICS_FILES, DAILY_FILE)
            },
            trade_count=count(self.trades),
            skipped_count=count(self.skipped),
        )


def _headline(metrics: Metrics) -> Headline:
    net: StrategyMetrics = metrics.strategy_net
    return Headline(
        total_pnl_rs=net.total_pnl_rs,
        roi=net.roi,
        cagr=net.cagr,
        max_drawdown_pct=net.max_drawdown_pct,
        sharpe_notional=net.sharpe_notional.value,
        sortino_notional=net.sortino_notional.value,
        trades=metrics.trades.trades,
        win_rate=metrics.trades.win_rate,
    )


def reject_constant(token: str) -> None:
    # json.loads accepts NaN / Infinity by default; a strict JSON file never contains them.
    raise ValueError(f"non-standard JSON value {token}")


def explain(name: str, exc: Exception) -> str:
    """A short description of what is wrong with a file (the first problem found)."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return f"{name}: {where}: {first['msg']} ({exc.error_count()} problem(s))"
    return f"{name}: {exc}"
