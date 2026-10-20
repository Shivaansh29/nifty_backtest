"""The backtest engine: one trade per real expiry, held to expiry (spec §5, v1).

For every row of the expiry calendar (M2) the engine:
  1. takes the entry day and the contracts labelled with the expiry printed that day
     (normally the real expiry; for a re-dated contract, its old stated date),
  2. asks the strategy which legs to trade,
  3. checks the legs can really be traded at that close: the contract exists, it traded that
     day (zero volume = stale close, never a fill) and its lot size is known; otherwise the
     week is SKIPPED with the reason logged,
  4. fills each leg at the official close, worse by the configured slippage,
  5. marks the position at every close until expiry (daily mark-to-market),
  6. settles at intrinsic value from NSE's final settlement level (trap 3),
  7. charges costs from the dated rate table and logs P&L three ways (spec §6):
     rupees (actual lot size), index points per unit, and % of premium collected.

Sign convention: P&L is from the option SELLER's point of view, so collecting premium is
positive and paying out intrinsic value at expiry is negative.
"""

from dataclasses import dataclass, field
from datetime import date

import duckdb
import pandas as pd

from nifty_backtest.costs.model import (
    Charges,
    CostConfig,
    RateTable,
    option_sale_charges,
    short_expiry_charges,
)
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.events import Event, events_between, load_events
from nifty_backtest.marketdata.indices import index_path
from nifty_backtest.marketdata.settlement import SettlementError, intrinsic_value, settlement_level
from nifty_backtest.marketdata.store import connect
from nifty_backtest.marketdata.trading_calendar import expiry_calendar, trading_days
from nifty_backtest.strategies.base import Leg, Strategy


@dataclass(frozen=True)
class RunConfig:
    data: DataConfig = field(default_factory=DataConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    capital_rs: float = 500_000.0
    underlying: str = "NIFTY"


@dataclass
class BacktestResult:
    trades: pd.DataFrame  # one row per completed trade
    marks: pd.DataFrame  # one row per trade per day held (entry .. expiry)
    equity: pd.DataFrame  # one row per trading day: capital + realised + open mark-to-market
    skipped: pd.DataFrame  # one row per expiry that was not traded, with the reason


class SkipWeek(Exception):
    """This week cannot be traded honestly; the message is the logged reason."""


@dataclass(frozen=True)
class OpenLeg:
    leg: Leg
    entry_close: float
    entry_fill: float
    quantity: int  # units = lot size x lots
    lot_size: int
    lot_size_source: str


def _leg_rows(chain: pd.DataFrame, legs: list[Leg]) -> list[pd.Series]:
    rows = []
    for leg in legs:
        match = chain[(chain["strike"] == leg.strike) & (chain["option_type"] == leg.option_type)]
        if match.empty:
            raise SkipWeek(f"leg_missing: {leg.option_type} {leg.strike:g}")
        row = match.iloc[0]
        if bool(row["zero_volume"]):
            raise SkipWeek(f"leg_zero_volume: {leg.option_type} {leg.strike:g}")
        if pd.isna(row["lot_size"]):
            raise SkipWeek(f"lot_size_unknown: {leg.option_type} {leg.strike:g}")
        rows.append(row)
    return rows


def _daily_closes(
    con: duckdb.DuckDBPyConnection, legs: list[Leg], entry: date, expiry: date, stated: date
) -> pd.DataFrame:
    """Closes of each leg's contract on every day strictly between entry and expiry.

    A re-dated contract keeps its strike and type but its expiry label changes, so both the
    stated and the actual expiry labels are accepted.
    """
    frames = []
    for leg in legs:
        frames.append(
            con.execute(
                """
                SELECT trade_date, ? AS option_type, close, zero_volume FROM options
                WHERE trade_date > ? AND trade_date < ? AND strike = ? AND option_type = ?
                  AND expiry IN (?, ?)
                """,
                [leg.option_type, entry, expiry, leg.strike, leg.option_type, stated, expiry],
            ).df()
        )
    closes = pd.concat(frames, ignore_index=True)
    if closes.duplicated(["trade_date", "option_type"]).any():
        raise SkipWeek("ambiguous_marks: a leg appears twice on one day")
    closes["trade_date"] = pd.to_datetime(closes["trade_date"]).dt.date
    return closes


def _trade(
    con: duckdb.DuckDBPyConnection,
    cfg: RunConfig,
    strategy: Strategy,
    rates: RateTable,
    index: pd.DataFrame,
    days: list[date],
    events: list[Event],
    cal: pd.Series,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    entry: date = cal["entry_date"]
    expiry: date = cal["expiry"]
    stated: date = cal["stated_expiry_on_entry"]
    if entry not in index.index or pd.isna(index.loc[entry]["nifty_close"]):
        raise SkipWeek("index_close_missing_on_entry")
    spot = float(index.loc[entry]["nifty_close"])

    chain = con.execute(
        "SELECT * FROM options WHERE underlying = ? AND trade_date = ? AND expiry = ?",
        [cfg.underlying, entry, stated],
    ).df()
    if chain.empty:
        raise SkipWeek("no_contracts_on_entry")
    legs = strategy.legs(chain, spot)
    rows = _leg_rows(chain, legs)
    try:
        level = settlement_level(con, expiry, cfg.underlying)
    except SettlementError:
        raise SkipWeek("settlement_level_missing") from None

    slip = cfg.costs.slippage_points_per_leg
    open_legs = []
    entry_charges = Charges()
    for leg, row in zip(legs, rows, strict=True):
        if leg.side != "sell":
            raise NotImplementedError("v1 engine only opens short legs")
        lot = int(row["lot_size"])
        quantity = lot * leg.lots
        close = float(row["close"])
        fill = max(close - slip, 0.0)  # a sell fills below the close by the slippage
        open_legs.append(OpenLeg(leg, close, fill, quantity, lot, str(row["lot_size_source"])))
        entry_charges = entry_charges + option_sale_charges(
            rates, cfg.costs, entry, fill * quantity
        )

    # Expiry: each leg is worth its intrinsic value at the settlement level. An in-the-money
    # short leg is assigned, which adds SEBI's fee on its notional value.
    expiry_charges = Charges()
    leg_values = {}
    for ol in open_legs:
        value = intrinsic_value(ol.leg.option_type, ol.leg.strike, level)
        leg_values[ol.leg.option_type] = value
        assigned_notional = level * ol.quantity if value > 0 else 0.0
        expiry_charges = expiry_charges + short_expiry_charges(rates, expiry, assigned_notional)
    charges = entry_charges + expiry_charges

    # P&L. All legs of a straddle share one quantity; enforce it so "points per unit" is exact.
    quantities = {ol.quantity for ol in open_legs}
    if len(quantities) != 1:
        raise SkipWeek("legs_have_different_quantities")
    quantity = quantities.pop()
    premium_close = sum(ol.entry_close for ol in open_legs)
    premium_fill = sum(ol.entry_fill for ol in open_legs)
    value_at_expiry = sum(leg_values.values())
    pnl_points_gross = premium_close - value_at_expiry
    pnl_rs_gross = pnl_points_gross * quantity
    slippage_rs = (premium_close - premium_fill) * quantity
    pnl_rs_net = (premium_fill - value_at_expiry) * quantity - charges.total
    pnl_points_net = pnl_rs_net / quantity

    # Daily marks: entry close, every close in between, then intrinsic value at expiry.
    closes = _daily_closes(con, legs, entry, expiry, stated)
    held_days = [d for d in days if entry < d < expiry]
    marks = []
    for day in [entry, *held_days, expiry]:
        if day == entry:
            values = {ol.leg.option_type: ol.entry_close for ol in open_legs}
            stale, missing = False, False
        elif day == expiry:
            values = dict(leg_values)
            stale, missing = False, False
        else:
            today = closes[closes["trade_date"] == day].set_index("option_type")
            values = {t: float(today.loc[t, "close"]) for t in today.index}
            stale = bool(today["zero_volume"].any())
            missing = set(values) != {ol.leg.option_type for ol in open_legs}
        mark = sum(values.values()) if not missing else float("nan")
        charged = entry_charges.total + (expiry_charges.total if day == expiry else 0.0)
        marks.append(
            {
                "trade_id": f"{cfg.underlying}-{expiry.isoformat()}",
                "expiry": expiry,
                "date": day,
                "ce_mark": values.get("CE", float("nan")),
                "pe_mark": values.get("PE", float("nan")),
                "position_value_points": mark,
                "mtm_points_gross": premium_close - mark,
                "mtm_rs_net": (premium_fill - mark) * quantity - charged,
                "stale_mark": stale,
                "missing_mark": missing,
            }
        )

    event_list = events_between(events, entry, expiry)
    vix = index.loc[entry]["vix_close"]
    first = open_legs[0]
    trade: dict[str, object] = {
        "trade_id": f"{cfg.underlying}-{expiry.isoformat()}",
        "underlying": cfg.underlying,
        "strategy": strategy.name,
        "entry_date": entry,
        "expiry": expiry,
        "expiry_weekday": f"{expiry:%a}",
        "stated_expiry_on_entry": stated,
        "relabelled": stated != expiry,
        "calendar_days_to_expiry": (expiry - entry).days,
        "trading_days_held": len(held_days) + 1,
        "strike": legs[0].strike,
        "nifty_close_at_entry": spot,
        "vix_at_entry": float(vix) if not pd.isna(vix) else float("nan"),
        "ce_entry_close": next(ol.entry_close for ol in open_legs if ol.leg.option_type == "CE"),
        "pe_entry_close": next(ol.entry_close for ol in open_legs if ol.leg.option_type == "PE"),
        "premium_close_points": premium_close,
        "premium_fill_points": premium_fill,
        "lot_size": first.lot_size,
        "lot_size_source": first.lot_size_source,
        "lots": first.leg.lots,
        "quantity": quantity,
        "settlement_level": level,
        "nifty_move_pct": (level / spot - 1) * 100,
        "ce_value_at_expiry": leg_values["CE"],
        "pe_value_at_expiry": leg_values["PE"],
        "value_at_expiry_points": value_at_expiry,
        "pnl_points_gross": pnl_points_gross,
        "pnl_points_net": pnl_points_net,
        "pnl_pct_premium_gross": pnl_points_gross / premium_close * 100,
        # % of premium collected: gross against the premium at the close, net against the
        # premium actually received (the fills, after slippage).
        "pnl_pct_premium_net": pnl_points_net / premium_fill * 100,
        "pnl_rs_gross": pnl_rs_gross,
        "slippage_rs": slippage_rs,
        "charges_rs": charges.total,
        "brokerage_rs": charges.brokerage,
        "stt_rs": charges.stt,
        "exchange_rs": charges.exchange,
        "ipft_rs": charges.ipft,
        "sebi_rs": charges.sebi,
        "stamp_rs": charges.stamp,
        "gst_rs": charges.gst,
        "pnl_rs_net": pnl_rs_net,
        "stale_marks": sum(m["stale_mark"] for m in marks),
        "missing_marks": sum(m["missing_mark"] for m in marks),
        "event_in_window": bool(event_list),
        "events": "; ".join(f"{e.type}@{e.day.isoformat()}" for e in event_list),
    }
    return trade, marks


def run_backtest(cfg: RunConfig, strategy: Strategy) -> BacktestResult:
    rates = RateTable(cfg.costs.rates_path)
    index = pd.read_parquet(index_path(cfg.data))
    index["date"] = pd.to_datetime(index["date"]).dt.date
    index = index.set_index("date")
    events = load_events(cfg.data)
    start, end = cfg.data.start, cfg.data.end_date(date.today())
    with connect(cfg.data) as con:
        # The calendar is built from all stored days (an entry may need days before `start`
        # to count back from); trades are kept only if they open and close inside the window.
        days = [d for d in trading_days(con) if start <= d <= end]
        calendar = expiry_calendar(
            con, cfg.data, strategy.entry_days_before_expiry, expiries_from=start, expiries_to=end
        )
        calendar = calendar[calendar["entry_date"].isna() | (calendar["entry_date"] >= start)]
        trades, marks, skipped = [], [], []
        for _, cal in calendar.iterrows():
            base = {"expiry": cal["expiry"], "entry_date": cal.get("entry_date")}
            if cal["status"] != "ok":
                skipped.append({**base, "reason": f"calendar_{cal['status']}"})
                continue
            try:
                trade, trade_marks = _trade(con, cfg, strategy, rates, index, days, events, cal)
            except SkipWeek as reason:
                skipped.append({**base, "reason": str(reason)})
                continue
            trades.append(trade)
            marks.extend(trade_marks)

    trades_df = pd.DataFrame(trades)
    marks_df = pd.DataFrame(marks)
    equity = _equity_curve(days, trades_df, marks_df, cfg.capital_rs)
    skipped_df = pd.DataFrame(skipped, columns=["expiry", "entry_date", "reason"])
    return BacktestResult(trades_df, marks_df, equity, skipped_df)


def _equity_curve(
    days: list[date], trades: pd.DataFrame, marks: pd.DataFrame, capital: float
) -> pd.DataFrame:
    """Account value at every close: capital + realised net P&L of finished trades +
    net mark-to-market of the open trade. A missing mark leaves that day's equity empty
    rather than filling it in."""
    if trades.empty:
        return pd.DataFrame({"date": days, "equity_rs": capital})
    realised_by_day = trades.groupby("expiry")["pnl_rs_net"].sum()
    open_marks = marks[marks["date"] != marks["expiry"]]  # expiry day counts as realised
    open_by_day = open_marks.groupby("date")["mtm_rs_net"].sum(min_count=1)
    rows, realised = [], 0.0
    for day in days:
        realised += float(realised_by_day.get(day, 0.0))
        open_mtm = open_by_day.get(day, 0.0)
        rows.append(
            {
                "date": day,
                "realised_rs": realised,
                "open_mtm_rs": open_mtm,
                "equity_rs": capital + realised + open_mtm,
            }
        )
    return pd.DataFrame(rows)
