"""Trading costs for option trades, from a dated, sourced rate table (spec §5).

Statutory and exchange rates come from reference/cost_rates.csv: each row has an
effective-from date and a primary source (NSE circular, SEBI regulation, Finance Act, GST
notification). For a trade on date D, the row in force is the latest one whose
effective_from <= D. Nothing in the logic below hardcodes a rate.

Brokerage and slippage are ASSUMPTIONS, not facts, so they live in CostConfig and every run
records the values it used.

What a short option position pays:
  at entry (one sell order per leg):
    brokerage (flat per order), STT on the premium (seller pays), NSE transaction charge,
    NSE IPFT contribution, SEBI fee, and 18% GST on brokerage + transaction charge + SEBI fee.
    No stamp duty: it is charged to the buyer only.
  on an early buy-back (M7 stop-loss / take-profit), one buy order per leg:
    brokerage, NSE transaction charge, IPFT, SEBI fee, stamp duty (buyer) and GST. No STT.
  at expiry (cash settlement, no order is placed):
    no brokerage and no STT (STT on exercise is payable by the purchaser, i.e. the option
    holder). If the short leg expires in the money it is assigned, and SEBI's fee also applies
    to the notional value of assigned contracts, plus GST on that fee.

Amounts are kept unrounded; contract notes round each line to the paisa, which changes totals
by at most a few paise per trade.
"""

import csv
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class CostConfig:
    """Assumptions that are the trader's choice, not the exchange's."""

    # Flat brokerage per executed order (a typical discount-broker model). Expiry settlement
    # places no order, so it pays no brokerage.
    brokerage_per_order_rs: float = 20.0
    # Each sell is assumed to fill this many index points BELOW the day's official close,
    # per unit, per leg: a cost of crossing the bid-ask spread at the close. An assumption;
    # M7 tests how results change with it.
    slippage_points_per_leg: float = 0.5
    rates_path: Path = Path("reference/cost_rates.csv")


@dataclass(frozen=True)
class Charges:
    """Rupee charges for one or more orders, line by line as on a contract note."""

    brokerage: float = 0.0
    stt: float = 0.0
    exchange: float = 0.0
    ipft: float = 0.0
    sebi: float = 0.0
    stamp: float = 0.0
    gst: float = 0.0

    @property
    def total(self) -> float:
        return float(sum(getattr(self, f.name) for f in fields(self)))

    def __add__(self, other: "Charges") -> "Charges":
        return Charges(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(self)))


@dataclass(frozen=True)
class RateRow:
    charge: str
    applies_to: str
    rate: float
    effective_from: date
    source: str


class RateTable:
    """The dated rate table, with a lookup by date."""

    def __init__(self, path: Path) -> None:
        with path.open(newline="", encoding="utf-8") as f:
            self.rows = [
                RateRow(
                    r["charge"],
                    r["applies_to"],
                    float(r["rate"]),
                    date.fromisoformat(r["effective_from"]),
                    r["source"].strip(),
                )
                for r in csv.DictReader(f)
            ]
        for row in self.rows:
            if not row.source:
                raise ValueError(f"{path.name}: {row.charge}/{row.applies_to} has no source")
            if not 0 <= row.rate < 1:
                raise ValueError(f"{path.name}: rate {row.rate} is not a fraction")
        keys = [(r.charge, r.applies_to, r.effective_from) for r in self.rows]
        if len(keys) != len(set(keys)):
            raise ValueError(f"{path.name}: two rows share a charge, scope and start date")

    def rate(self, charge: str, applies_to: str, on: date) -> float:
        candidates = [
            r
            for r in self.rows
            if r.charge == charge and r.applies_to == applies_to and r.effective_from <= on
        ]
        if not candidates:
            raise LookupError(f"no {charge}/{applies_to} rate in force on {on}")
        return max(candidates, key=lambda r: r.effective_from).rate


def option_sale_charges(table: RateTable, cfg: CostConfig, on: date, premium_rs: float) -> Charges:
    """Charges for ONE sell order of an option, `premium_rs` = fill price x quantity."""
    brokerage = cfg.brokerage_per_order_rs
    exchange = table.rate("exchange_txn", "option_trade", on) * premium_rs
    sebi = table.rate("sebi_fee", "option_trade", on) * premium_rs
    return Charges(
        brokerage=brokerage,
        stt=table.rate("stt", "option_sale", on) * premium_rs,
        exchange=exchange,
        ipft=table.rate("ipft", "option_trade", on) * premium_rs,
        sebi=sebi,
        gst=table.rate("gst", "services", on) * (brokerage + exchange + sebi),
    )


def option_purchase_charges(
    table: RateTable, cfg: CostConfig, on: date, premium_rs: float
) -> Charges:
    """Charges for ONE buy order of an option (M7: buying back a short leg before expiry),
    `premium_rs` = fill price x quantity. The buyer pays stamp duty; there is no STT on a
    purchase (option STT is on the sale, and on exercise for the holder)."""
    brokerage = cfg.brokerage_per_order_rs
    exchange = table.rate("exchange_txn", "option_trade", on) * premium_rs
    sebi = table.rate("sebi_fee", "option_trade", on) * premium_rs
    return Charges(
        brokerage=brokerage,
        exchange=exchange,
        ipft=table.rate("ipft", "option_trade", on) * premium_rs,
        sebi=sebi,
        stamp=table.rate("stamp_duty", "option_purchase", on) * premium_rs,
        gst=table.rate("gst", "services", on) * (brokerage + exchange + sebi),
    )


def short_expiry_charges(table: RateTable, on: date, assigned_notional_rs: float) -> Charges:
    """Charges when a SHORT option leg is cash-settled at expiry.

    `assigned_notional_rs` is settlement level x quantity if the leg expired in the money
    (it is assigned), else 0. No brokerage (no order) and no STT (the purchaser pays it).
    """
    sebi = table.rate("sebi_fee", "option_assignment", on) * assigned_notional_rs
    return Charges(sebi=sebi, gst=table.rate("gst", "services", on) * sebi)
