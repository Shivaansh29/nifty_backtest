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

M7 research conditions (engine/conditions.py), all OFF by default so the baseline is
unchanged: entry filters on previous-close information (VIX, ADX, knowable scheduled
events), an alternative strike reference (the previous session's NIFTY close), and early
exits of individual legs from their daily high/low. Their extra trade and mark columns are
written only when they are active.
"""

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import duckdb
import pandas as pd

from nifty_backtest.costs.model import (
    Charges,
    CostConfig,
    RateTable,
    option_purchase_charges,
    option_sale_charges,
    short_expiry_charges,
)
from nifty_backtest.engine.conditions import (
    Bar,
    EntryFilter,
    ExitRule,
    LegExit,
    entry_filter_reason,
    find_exit,
)
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.events import (
    Event,
    events_between,
    knowable_events_between,
    load_events,
)
from nifty_backtest.marketdata.indicators import previous_session, wilder_adx
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
    # M7 research conditions; the defaults are the baseline.
    entry_filter: EntryFilter | None = None
    exit_rule: ExitRule | None = None
    # Which NIFTY level picks the strike: the entry day's close (baseline; known only after
    # the close) or the previous session's close (known before the entry day).
    strike_reference: Literal["entry_close", "previous_close"] = "entry_close"


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


def _daily_bars(
    con: duckdb.DuckDBPyConnection, legs: list[Leg], entry: date, expiry: date, stated: date
) -> dict[str, list[Bar]]:
    """Open, high and low of each leg's contract on every session after entry up to and
    including expiry day (for early exits). A row with any of them missing is treated like a
    zero-volume day: it carries no information about the day's range."""
    bars: dict[str, list[Bar]] = {}
    for leg in legs:
        rows = con.execute(
            """
            SELECT trade_date, open, high, low, zero_volume FROM options
            WHERE trade_date > ? AND trade_date <= ? AND strike = ? AND option_type = ?
              AND expiry IN (?, ?)
            ORDER BY trade_date
            """,
            [entry, expiry, leg.strike, leg.option_type, stated, expiry],
        ).df()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        if rows["trade_date"].duplicated().any():
            raise SkipWeek("ambiguous_bars: a leg appears twice on one day")
        bars[leg.option_type] = [
            Bar(day, float(o), float(h), float(lo), bool(z) or any(pd.isna(v) for v in (o, h, lo)))
            for day, o, h, lo, z in zip(
                rows["trade_date"].tolist(),
                rows["open"].tolist(),
                rows["high"].tolist(),
                rows["low"].tolist(),
                rows["zero_volume"].tolist(),
                strict=True,
            )
        ]
    return bars


def _trade(
    con: duckdb.DuckDBPyConnection,
    cfg: RunConfig,
    strategy: Strategy,
    rates: RateTable,
    index: pd.DataFrame,
    days: list[date],
    events: list[Event],
    cal: pd.Series,
    all_days: list[date],
    adx: pd.Series | None,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    entry: date = cal["entry_date"]
    expiry: date = cal["expiry"]
    stated: date = cal["stated_expiry_on_entry"]
    if entry not in index.index or pd.isna(index.loc[entry]["nifty_close"]):
        raise SkipWeek("index_close_missing_on_entry")
    spot = float(index.loc[entry]["nifty_close"])
    # Information day: the previous session's close (t-1). Filters and the alternative
    # strike reference may use only what was known then.
    info_day = previous_session(all_days, entry)
    extra: dict[str, object] = {}  # columns written only when a research condition is on

    def at_info_day(column: str) -> float:
        if info_day is None or info_day not in index.index:
            return math.nan
        value = index.loc[info_day][column]
        return math.nan if pd.isna(value) else float(value)

    if cfg.entry_filter is not None:
        vix_prev = at_info_day("vix_close")
        adx_prev = float(adx[info_day]) if adx is not None and info_day in adx.index else math.nan
        knowable = knowable_events_between(events, entry, expiry, info_day) if info_day else []
        reason = entry_filter_reason(cfg.entry_filter, vix_prev, adx_prev, len(knowable))
        if reason:
            raise SkipWeek(reason)
        extra.update(
            {
                "info_date": info_day,
                "vix_prev_close": vix_prev,
                "adx_prev": adx_prev,
                "knowable_events": "; ".join(f"{e.type}@{e.day.isoformat()}" for e in knowable),
            }
        )
    strike_level = spot
    if cfg.strike_reference == "previous_close":
        strike_level = at_info_day("nifty_close")
        if math.isnan(strike_level):
            raise SkipWeek("index_close_missing_on_previous_session")
        extra["strike_reference_level"] = strike_level
    elif cfg.strike_reference != "entry_close":
        raise ValueError(f"unknown strike_reference {cfg.strike_reference!r}")

    chain = con.execute(
        "SELECT * FROM options WHERE underlying = ? AND trade_date = ? AND expiry = ?",
        [cfg.underlying, entry, stated],
    ).df()
    if chain.empty:
        raise SkipWeek("no_contracts_on_entry")
    legs = strategy.legs(chain, strike_level)
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

    # Early exits (M7, off by default): a leg bought back before expiry is worth its trigger
    # price (gross) and costs the trigger price plus slippage (net), with purchase charges.
    exits: dict[str, LegExit] = {}
    no_info_days = 0
    if cfg.exit_rule is not None:
        bars = _daily_bars(con, legs, entry, expiry, stated)
        sessions = [d for d in days if entry < d <= expiry]
        for ol in open_legs:
            leg_bars = bars.get(ol.leg.option_type, [])
            found, no_info = find_exit(cfg.exit_rule, ol.entry_fill, leg_bars)
            last = found.day if found else expiry
            seen = {b.day for b in leg_bars}
            no_info_days += no_info + sum(1 for d in sessions if d <= last and d not in seen)
            if found:
                exits[ol.leg.option_type] = found

    # Expiry: each leg still open is worth its intrinsic value at the settlement level. An
    # in-the-money short leg is assigned, which adds SEBI's fee on its notional value.
    expiry_charges = Charges()
    exit_charges = Charges()
    leg_values = {}  # per unit, gross: exit trigger price or intrinsic value
    leg_paid = {}  # per unit, what the seller actually pays: buy-back fill or intrinsic value
    for ol in open_legs:
        kind = ol.leg.option_type
        if kind in exits:
            buy_fill = exits[kind].price + slip  # a buy fills above the price by the slippage
            leg_values[kind] = exits[kind].price
            leg_paid[kind] = buy_fill
            exit_charges = exit_charges + option_purchase_charges(
                rates, cfg.costs, exits[kind].day, buy_fill * ol.quantity
            )
            continue
        value = intrinsic_value(kind, ol.leg.strike, level)
        leg_values[kind] = value
        leg_paid[kind] = value
        assigned_notional = level * ol.quantity if value > 0 else 0.0
        expiry_charges = expiry_charges + short_expiry_charges(rates, expiry, assigned_notional)
    charges = entry_charges + exit_charges + expiry_charges

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
    slippage_rs = (premium_close - premium_fill) * quantity + slip * len(exits) * quantity
    pnl_rs_net = (premium_fill - sum(leg_paid.values())) * quantity - charges.total
    pnl_points_net = pnl_rs_net / quantity

    # Daily marks: entry close, every close in between, then intrinsic value at expiry.
    closes = _daily_closes(con, legs, entry, expiry, stated)
    held_days = [d for d in days if entry < d < expiry]
    marks = []
    for day in [entry, *held_days, expiry]:
        closed = {t: e for t, e in exits.items() if e.day <= day}
        if day == entry:
            values = {ol.leg.option_type: ol.entry_close for ol in open_legs}
            paid = dict(values)
            stale, missing = False, False
        elif day == expiry:
            values = dict(leg_values)
            paid = dict(leg_paid)
            stale, missing = False, False
        else:
            today = closes[closes["trade_date"] == day].set_index("option_type")
            today = today[~today.index.isin(list(closed))]  # a closed leg needs no price
            values = {t: float(today.loc[t, "close"]) for t in today.index}
            paid = dict(values)
            for kind, ex in closed.items():  # a closed leg stays at its exit price
                values[kind] = ex.price
                paid[kind] = ex.price + slip
            stale = bool(today["zero_volume"].any())
            missing = set(values) != {ol.leg.option_type for ol in open_legs}
        mark = sum(values.values()) if not missing else float("nan")
        paid_mark = sum(paid.values()) if not missing else float("nan")
        exit_charged = sum(
            option_purchase_charges(rates, cfg.costs, ex.day, (ex.price + slip) * quantity).total
            for ex in closed.values()
        )
        charged = (
            entry_charges.total + exit_charged + (expiry_charges.total if day == expiry else 0.0)
        )
        mark_row: dict[str, object] = {
            "trade_id": f"{cfg.underlying}-{expiry.isoformat()}",
            "expiry": expiry,
            "date": day,
            "ce_mark": values.get("CE", float("nan")),
            "pe_mark": values.get("PE", float("nan")),
            "position_value_points": mark,
            "mtm_points_gross": premium_close - mark,
            "mtm_rs_net": (premium_fill - paid_mark) * quantity - charged,
            "stale_mark": stale,
            "missing_mark": missing,
        }
        if cfg.exit_rule is not None:
            mark_row["ce_closed"] = "CE" in closed
            mark_row["pe_closed"] = "PE" in closed
        marks.append(mark_row)

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
    if cfg.exit_rule is not None:
        for kind in ("CE", "PE"):
            ex = exits.get(kind)
            trade[f"{kind.lower()}_exit_date"] = ex.day if ex else expiry
            trade[f"{kind.lower()}_exit_reason"] = ex.reason if ex else "expiry"
            trade[f"{kind.lower()}_exit_price"] = leg_values[kind]
        trade["exit_charges_rs"] = exit_charges.total
        trade["no_info_days"] = no_info_days
    trade.update(extra)
    return trade, marks


def run_backtest(cfg: RunConfig, strategy: Strategy) -> BacktestResult:
    rates = RateTable(cfg.costs.rates_path)
    index = pd.read_parquet(index_path(cfg.data))
    index["date"] = pd.to_datetime(index["date"]).dt.date
    index = index.set_index("date")
    events = load_events(cfg.data)
    start, end = cfg.data.start, cfg.data.end_date(date.today())
    adx: pd.Series | None = None
    if cfg.entry_filter is not None and cfg.entry_filter.adx_max is not None:
        adx = wilder_adx(
            index["nifty_high"],
            index["nifty_low"],
            index["nifty_close"],
            cfg.entry_filter.adx_period,
        )
    with connect(cfg.data) as con:
        # The calendar is built from all stored days (an entry may need days before `start`
        # to count back from); trades are kept only if they open and close inside the window.
        all_days = trading_days(con)
        days = [d for d in all_days if start <= d <= end]
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
                trade, trade_marks = _trade(
                    con, cfg, strategy, rates, index, days, events, cal, all_days, adx
                )
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
