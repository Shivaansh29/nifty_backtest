"""The engine's signed multi-leg path (M9 plan §5, §6, §9.1-§9.3).

Used for strategies with `multi_leg = True` (the iron condor). The short straddle keeps the
original path in backtest.py unchanged, so B0 reproduces its reference run byte for byte.

Every leg has a side s: +1 sold (premium received), -1 bought (premium paid). For leg i with
official entry close c_i, fill f_i and intrinsic value L_i at the settlement level:
  fill        f_i = max(c_i - slip, 0) if sold;  c_i + slip if bought
  credit      C_close = sum s_i c_i;  C_fill = sum s_i f_i
  at expiry   V = sum s_i L_i
  gross       (C_close - V) x quantity
  net         (C_fill - V) x quantity - charges
Charges are per leg and never netted across a spread: each order pays its own entry charges,
an in-the-money sold leg is assigned (SEBI fee on notional) and an in-the-money bought leg is
exercised (STT on intrinsic value + SEBI fee on notional).

Entry eligibility (plan §2.3), in this order: E1-E3 inside the strategy (reference ATM missing
or zero volume, degenerate strikes); E4 any leg missing; E5 any leg zero volume; E6 a lot size
unknown or the legs' quantities differ; E7 settlement level missing; E8 credit at the close
<= 0, or no risk left to measure (widest wing - filled credit <= 0).

After entry, liquidity never removes a trade (that would use information from after entry):
a zero-volume leg makes the day a stale mark, a missing row a missing mark whose position
value, mark-to-market and equity stay empty, never filled.

Reference chain without look-ahead (plan §9.1): with strike_reference = "previous_close" the
strategy sees only the previous session's rows and NIFTY close; the legs it returns are then
checked and filled against the entry day's chain only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import duckdb
import pandas as pd

from nifty_backtest.costs.model import (
    Charges,
    RateTable,
    long_expiry_charges,
    option_purchase_charges,
    option_sale_charges,
    short_expiry_charges,
)
from nifty_backtest.marketdata.events import Event, events_between
from nifty_backtest.marketdata.indicators import previous_session
from nifty_backtest.marketdata.settlement import SettlementError, intrinsic_value, settlement_level
from nifty_backtest.strategies.base import Leg, SkipWeek, Strategy

if TYPE_CHECKING:
    from nifty_backtest.engine.backtest import RunConfig

CHARGE_LINES = ("brokerage", "stt", "exchange", "ipft", "sebi", "stamp", "gst")
LEG_COLUMNS = [
    "trade_id",
    "leg_id",
    "side",
    "option_type",
    "strike",
    "entry_close",
    "entry_fill",
    "quantity",
    "lot_size",
    "lot_size_source",
    "intrinsic_at_expiry",
    "expiry_status",
    "pnl_points_gross",
    "pnl_rs_gross",
    "slippage_rs",
    "charges_rs",
    *(f"{line}_rs" for line in CHARGE_LINES),
    "pnl_rs_net",
]
LEG_MARK_COLUMNS = ["trade_id", "leg_id", "date", "close", "stale", "missing"]
Row = dict[str, object]


@dataclass(frozen=True)
class FilledLeg:
    leg: Leg
    entry_close: float
    entry_fill: float
    quantity: int
    lot_size: int
    lot_size_source: str


def _query_chain(
    con: duckdb.DuckDBPyConnection, underlying: str, day: date, expiries: list[date]
) -> pd.DataFrame:
    marks = ", ".join("?" for _ in expiries)
    return con.execute(
        f"SELECT * FROM options WHERE underlying = ? AND trade_date = ? AND expiry IN ({marks})",
        [underlying, day, *expiries],
    ).df()


def _entry_rows(chain: pd.DataFrame, legs: list[Leg]) -> list[pd.Series]:
    """E4, E5, E6 against the entry day's chain, each rule over every leg before the next."""
    rows = []
    for leg in legs:
        match = chain[(chain["strike"] == leg.strike) & (chain["option_type"] == leg.option_type)]
        if match.empty:
            raise SkipWeek(f"leg_missing: {leg.leg_id}")
        rows.append(match.iloc[0])
    for leg, row in zip(legs, rows, strict=True):
        if bool(row["zero_volume"]):
            raise SkipWeek(f"leg_zero_volume: {leg.leg_id}")
    for leg, row in zip(legs, rows, strict=True):
        if pd.isna(row["lot_size"]):
            raise SkipWeek(f"lot_size_unknown: {leg.leg_id}")
    return rows


def wing_widths(legs: list[Leg]) -> dict[str, float | None]:
    """Width of each side's spread (long strike - short strike, in points), if that side has
    exactly one sold and one bought leg; otherwise None (no defined wing)."""
    widths: dict[str, float | None] = {}
    for kind in ("CE", "PE"):
        sold = [leg for leg in legs if leg.option_type == kind and leg.side == "sell"]
        bought = [leg for leg in legs if leg.option_type == kind and leg.side == "buy"]
        one_each = len(sold) == 1 and len(bought) == 1
        widths[kind] = abs(bought[0].strike - sold[0].strike) if one_each else None
    return widths


def _leg_closes(
    con: duckdb.DuckDBPyConnection, legs: list[Leg], entry: date, expiry: date, stated: date
) -> dict[tuple[str, date], tuple[float, bool]]:
    """(close, zero_volume) of each leg's contract on every day strictly between entry and
    expiry, keyed by (leg_id, day). Both the stated and the actual expiry labels are accepted,
    as in the straddle path, because NSE re-dates contracts."""
    out: dict[tuple[str, date], tuple[float, bool]] = {}
    for leg in legs:
        rows = con.execute(
            """
            SELECT trade_date, close, zero_volume FROM options
            WHERE trade_date > ? AND trade_date < ? AND strike = ? AND option_type = ?
              AND expiry IN (?, ?)
            """,
            [entry, expiry, leg.strike, leg.option_type, stated, expiry],
        ).df()
        rows["trade_date"] = pd.to_datetime(rows["trade_date"]).dt.date
        if rows["trade_date"].duplicated().any():
            raise SkipWeek(f"ambiguous_marks: {leg.leg_id} appears twice on one day")
        for day, close, zero in zip(
            rows["trade_date"], rows["close"], rows["zero_volume"], strict=True
        ):
            out[(leg.leg_id, day)] = (float(close), bool(zero))
    return out


def _charge_columns(charges: Charges) -> dict[str, float]:
    return {f"{line}_rs": getattr(charges, line) for line in CHARGE_LINES}


def trade_multileg(
    con: duckdb.DuckDBPyConnection,
    cfg: RunConfig,
    strategy: Strategy,
    rates: RateTable,
    index: pd.DataFrame,
    days: list[date],
    events: list[Event],
    cal: pd.Series,
    all_days: list[date],
) -> tuple[Row, list[Row], list[Row], list[Row]]:
    """One multi-leg trade: (trade row, daily marks, leg rows, leg marks)."""
    entry: date = cal["entry_date"]
    expiry: date = cal["expiry"]
    stated: date = cal["stated_expiry_on_entry"]
    trade_id = f"{cfg.underlying}-{expiry.isoformat()}"
    if entry not in index.index or pd.isna(index.loc[entry]["nifty_close"]):
        raise SkipWeek("index_close_missing_on_entry")
    spot = float(index.loc[entry]["nifty_close"])
    extra: dict[str, object] = {}

    # --- reference day: what the strategy may look at --------------------------------------
    entry_chain: pd.DataFrame | None = None
    if cfg.strike_reference == "previous_close":
        ref_day = previous_session(all_days, entry)
        if ref_day is None or ref_day not in index.index:
            raise SkipWeek("index_close_missing_on_previous_session")
        level = index.loc[ref_day]["nifty_close"]
        if pd.isna(level):
            raise SkipWeek("index_close_missing_on_previous_session")
        ref_level = float(level)
        ref_chain = _query_chain(con, cfg.underlying, ref_day, sorted({stated, expiry}))
        if ref_chain.empty:
            raise SkipWeek("reference_chain_missing")
        if ref_chain.duplicated(["strike", "option_type"]).any():
            raise SkipWeek("ambiguous_reference_chain")
        extra["strike_reference_level"] = ref_level
    elif cfg.strike_reference == "entry_close":
        ref_day, ref_level = entry, spot
        entry_chain = _query_chain(con, cfg.underlying, entry, [stated])
        if entry_chain.empty:
            raise SkipWeek("no_contracts_on_entry")
        ref_chain = entry_chain
    else:
        raise ValueError(f"unknown strike_reference {cfg.strike_reference!r}")
    reference = strategy.reference(ref_chain, ref_level)  # E1, E2
    legs = strategy.legs(ref_chain, ref_level)  # E3
    if len({leg.leg_id for leg in legs}) != len(legs):
        raise ValueError(f"{strategy.name}: two legs share one contract")

    # --- entry day: can these legs really be traded at this close? -------------------------
    if entry_chain is None:
        entry_chain = _query_chain(con, cfg.underlying, entry, [stated])
        if entry_chain.empty:
            raise SkipWeek("no_contracts_on_entry")
    rows = _entry_rows(entry_chain, legs)  # E4, E5, E6 (lot size)
    quantities = {int(row["lot_size"]) * leg.lots for leg, row in zip(legs, rows, strict=True)}
    if len(quantities) != 1:
        raise SkipWeek("legs_have_different_quantities")  # E6
    quantity = quantities.pop()
    try:
        level = settlement_level(con, expiry, cfg.underlying)  # E7
    except SettlementError:
        raise SkipWeek("settlement_level_missing") from None

    slip = cfg.costs.slippage_points_per_leg
    filled = []
    for leg, row in zip(legs, rows, strict=True):
        close = float(row["close"])
        fill = max(close - slip, 0.0) if leg.side == "sell" else close + slip
        filled.append(
            FilledLeg(leg, close, fill, quantity, int(row["lot_size"]), str(row["lot_size_source"]))
        )
    credit_close = sum(f.leg.sign * f.entry_close for f in filled)
    credit_fill = sum(f.leg.sign * f.entry_fill for f in filled)
    if credit_close <= 0:
        raise SkipWeek(f"no_positive_credit: {credit_close:g} points at the close")  # E8
    widths = wing_widths(legs)
    defined = [w for w in widths.values() if w is not None]
    max_loss = max(defined) - credit_fill if defined else math.nan
    if defined and max_loss <= 0:
        raise SkipWeek(f"no_defined_risk: widest wing {max(defined):g} <= credit")  # E8

    # --- costs and settlement, leg by leg ---------------------------------------------------
    leg_rows: list[dict[str, object]] = []
    entry_charges = Charges()
    expiry_charges = Charges()
    value_at_expiry = 0.0
    for f in filled:
        sign, kind, strike = f.leg.sign, f.leg.option_type, f.leg.strike
        premium_rs = f.entry_fill * quantity
        if f.leg.side == "sell":
            opened = option_sale_charges(rates, cfg.costs, entry, premium_rs)
        else:
            opened = option_purchase_charges(rates, cfg.costs, entry, premium_rs)
        intrinsic = intrinsic_value(kind, strike, level)
        notional = level * quantity if intrinsic > 0 else 0.0
        if f.leg.side == "sell":
            settled = short_expiry_charges(rates, expiry, notional)
            status = "assigned" if intrinsic > 0 else "worthless"
        else:
            settled = long_expiry_charges(rates, expiry, intrinsic * quantity, notional)
            status = "exercised" if intrinsic > 0 else "worthless"
        entry_charges = entry_charges + opened
        expiry_charges = expiry_charges + settled
        value_at_expiry += sign * intrinsic
        leg_charges = opened + settled
        leg_rows.append(
            {
                "trade_id": trade_id,
                "leg_id": f.leg.leg_id,
                "side": f.leg.side,
                "option_type": kind,
                "strike": strike,
                "entry_close": f.entry_close,
                "entry_fill": f.entry_fill,
                "quantity": quantity,
                "lot_size": f.lot_size,
                "lot_size_source": f.lot_size_source,
                "intrinsic_at_expiry": intrinsic,
                "expiry_status": status,
                "pnl_points_gross": sign * (f.entry_close - intrinsic),
                "pnl_rs_gross": sign * (f.entry_close - intrinsic) * quantity,
                "slippage_rs": sign * (f.entry_close - f.entry_fill) * quantity,
                "charges_rs": leg_charges.total,
                **_charge_columns(leg_charges),
                "pnl_rs_net": sign * (f.entry_fill - intrinsic) * quantity - leg_charges.total,
            }
        )
    charges = entry_charges + expiry_charges
    pnl_points_gross = credit_close - value_at_expiry
    pnl_rs_net = (credit_fill - value_at_expiry) * quantity - charges.total
    pnl_points_net = pnl_rs_net / quantity
    premium = reference["reference_premium_points"]

    # --- daily marks --------------------------------------------------------------------------
    closes = _leg_closes(con, legs, entry, expiry, stated)
    held_days = [d for d in days if entry < d < expiry]
    marks: list[dict[str, object]] = []
    leg_marks: list[dict[str, object]] = []
    legs_stale_days = 0
    for day in [entry, *held_days, expiry]:
        values: dict[str, float] = {}
        stale = missing = False
        for f in filled:
            leg_id = f.leg.leg_id
            leg_stale = leg_missing = False
            if day == entry:
                value = f.entry_close
            elif day == expiry:
                value = intrinsic_value(f.leg.option_type, f.leg.strike, level)
            elif (leg_id, day) in closes:
                value, leg_stale = closes[(leg_id, day)]
            else:
                value, leg_missing = math.nan, True
            values[leg_id] = value
            stale, missing = stale or leg_stale, missing or leg_missing
            legs_stale_days += leg_stale
            leg_marks.append(
                {
                    "trade_id": trade_id,
                    "leg_id": leg_id,
                    "date": day,
                    "close": value,
                    "stale": leg_stale,
                    "missing": leg_missing,
                }
            )
        position = math.nan if missing else sum(f.leg.sign * values[f.leg.leg_id] for f in filled)
        charged = entry_charges.total + (expiry_charges.total if day == expiry else 0.0)
        marks.append(
            {
                "trade_id": trade_id,
                "expiry": expiry,
                "date": day,
                "ce_mark": math.nan,  # one-leg-per-type columns: blank for multi-leg trades
                "pe_mark": math.nan,
                "position_value_points": position,
                "mtm_points_gross": credit_close - position,
                "mtm_rs_net": (credit_fill - position) * quantity - charged,
                "stale_mark": stale,
                "missing_mark": missing,
            }
        )

    # --- the trade row: the straddle's columns in the same order, then the multi-leg ones ---
    event_list = events_between(events, entry, expiry)
    vix = index.loc[entry]["vix_close"]
    first = filled[0]
    trade: dict[str, object] = {
        "trade_id": trade_id,
        "underlying": cfg.underlying,
        "strategy": strategy.name,
        "entry_date": entry,
        "expiry": expiry,
        "expiry_weekday": f"{expiry:%a}",
        "stated_expiry_on_entry": stated,
        "relabelled": stated != expiry,
        "calendar_days_to_expiry": (expiry - entry).days,
        "trading_days_held": len(held_days) + 1,
        "strike": math.nan,  # never filled with a made-up "main" strike (plan §9.3)
        "nifty_close_at_entry": spot,
        "vix_at_entry": float(vix) if not pd.isna(vix) else math.nan,
        "ce_entry_close": math.nan,
        "pe_entry_close": math.nan,
        "premium_close_points": credit_close,  # net credit at the close
        "premium_fill_points": credit_fill,  # net credit received, after slippage
        "lot_size": first.lot_size,
        "lot_size_source": first.lot_size_source,
        "lots": first.leg.lots,
        "quantity": quantity,
        "settlement_level": level,
        "nifty_move_pct": (level / spot - 1) * 100,
        "ce_value_at_expiry": math.nan,
        "pe_value_at_expiry": math.nan,
        "value_at_expiry_points": value_at_expiry,
        "pnl_points_gross": pnl_points_gross,
        "pnl_points_net": pnl_points_net,
        # "% of premium" for a multi-leg trade is % of NET CREDIT (plan §5): reported, never
        # the primary measure, because credit differs about threefold between variants.
        "pnl_pct_premium_gross": pnl_points_gross / credit_close * 100,
        "pnl_pct_premium_net": pnl_points_net / credit_fill * 100,
        "pnl_rs_gross": pnl_points_gross * quantity,
        "slippage_rs": (credit_close - credit_fill) * quantity,
        "charges_rs": charges.total,
        **_charge_columns(charges),
        "pnl_rs_net": pnl_rs_net,
        "stale_marks": sum(bool(m["stale_mark"]) for m in marks),
        "missing_marks": sum(bool(m["missing_mark"]) for m in marks),
        "event_in_window": bool(event_list),
        "events": "; ".join(f"{e.type}@{e.day.isoformat()}" for e in event_list),
        "reference_atm": reference["reference_atm"],
        "reference_premium_points": premium,
        "reference_date": ref_day,
        "wing_call_points": widths["CE"] if widths["CE"] is not None else math.nan,
        "wing_put_points": widths["PE"] if widths["PE"] is not None else math.nan,
        "max_loss_points": max_loss,
        "pnl_pct_reference_premium_net": 100 * pnl_points_net / premium,  # R_P, primary
        "pnl_pct_max_loss_net": 100 * pnl_points_net / max_loss if defined else math.nan,  # R_ML
        "legs_stale_days": legs_stale_days,
    }
    trade.update(extra)
    return trade, marks, leg_rows, leg_marks
