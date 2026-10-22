"""Daily series rebuilt from a saved run (trades.csv, marks.csv, equity.csv).

Metrics are computed from the SAVED run, not from a live engine, so any run can be re-analysed
later and the numbers trace back to files on disk.

Four daily series:
  rupee_net      the run's equity curve (capital + realised + open mark-to-market, after costs)
  rupee_gross    the same curve rebuilt WITHOUT slippage and charges (for "with vs without costs")
  notional_net   return on notional, the approved headline basis for Sharpe/Sortino:
                 r_t = sum over open trades of (change in net P&L per unit that day) / (NIFTY
                 close at that trade's entry). Net P&L per unit = net rupee mark / quantity, so
                 slippage and charges are included (entry costs on the entry day, expiry costs
                 on expiry day). It does not depend on the lot size.
  notional_gross the same without slippage and charges
A day with no open position has return 0. A missing mark makes that day (and the next day's
change) missing: it is never filled in.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RunData:
    folder: Path
    trades: pd.DataFrame
    marks: pd.DataFrame
    equity: pd.DataFrame
    capital: float
    config: dict[str, Any]
    manifest: dict[str, Any]

    @property
    def days(self) -> list[date]:
        return list(self.equity["date"])


def _as_dates(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        frame[column] = pd.to_datetime(frame[column]).dt.date
    return frame


def load_run(folder: Path) -> RunData:
    config = json.loads((folder / "config.json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    trades = pd.read_csv(folder / "trades.csv")
    if not trades.empty:
        trades = _as_dates(trades, ["entry_date", "expiry"])
    marks = pd.read_csv(folder / "marks.csv")
    if not marks.empty:
        marks = _as_dates(marks, ["date", "expiry"])
    equity = _as_dates(pd.read_csv(folder / "equity.csv"), ["date"])
    return RunData(
        folder, trades, marks, equity, float(config["run"]["capital_rs"]), config, manifest
    )


def sum_keep_gaps(values: pd.Series) -> float:
    """Sum that stays missing if any part is missing (pandas would silently skip NaN)."""
    return float(values.sum()) if values.notna().all() else float("nan")


def rupee_net(run: RunData) -> pd.Series:
    return pd.Series(run.equity["equity_rs"].to_numpy(), index=run.days, name="rupee_net")


def rupee_gross(run: RunData) -> pd.Series:
    """Equity without slippage and charges: capital + realised gross P&L + open gross marks."""
    if run.trades.empty:
        return pd.Series(run.capital, index=run.days, name="rupee_gross")
    realised = run.trades.groupby("expiry")["pnl_rs_gross"].sum()
    marks = run.marks.merge(run.trades[["trade_id", "quantity"]], on="trade_id")
    open_marks = marks[marks["date"] != marks["expiry"]].copy()
    open_marks["gross_rs"] = open_marks["mtm_points_gross"] * open_marks["quantity"]
    open_by_day = open_marks.groupby("date")["gross_rs"].agg(sum_keep_gaps)
    values, booked = [], 0.0
    for day in run.days:
        booked += float(realised.get(day, 0.0))
        values.append(run.capital + booked + float(open_by_day.get(day, 0.0)))
    return pd.Series(values, index=run.days, name="rupee_gross")


def rupee_returns(equity: pd.Series, capital: float) -> pd.Series:
    """r_t = E_t / E_(t-1) - 1; the first day is measured against the starting capital."""
    previous = equity.shift(1)
    previous.iloc[0] = capital
    return equity / previous - 1


def notional_returns(run: RunData, net: bool = True) -> pd.Series:
    name = "notional_net" if net else "notional_gross"
    if run.trades.empty:
        return pd.Series(0.0, index=run.days, name=name)
    info = run.trades[["trade_id", "quantity", "nifty_close_at_entry"]]
    marks = run.marks.merge(info, on="trade_id").sort_values(["trade_id", "date"])
    per_unit = marks["mtm_rs_net"] / marks["quantity"] if net else marks["mtm_points_gross"]
    marks["per_unit"] = per_unit
    change = marks.groupby("trade_id")["per_unit"].diff()
    first_day = marks.groupby("trade_id").cumcount() == 0
    # Before the entry the trade's P&L is 0, so on the entry day the change is the mark itself.
    marks["change"] = change.where(~first_day, marks["per_unit"])
    marks["return"] = marks["change"] / marks["nifty_close_at_entry"]
    by_day = marks.groupby("date")["return"].agg(sum_keep_gaps)
    # Days without any trade are flat (return 0); a missing mark stays missing.
    return by_day.reindex(run.days, fill_value=0.0).rename(name)
