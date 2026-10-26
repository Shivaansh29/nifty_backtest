"""Optional trading conditions for M7 research: entry filters and early exits.

Both are OFF by default, so a run without them is exactly the M3-M6 baseline. Each is a
rule the engine applies to any strategy (the strategy interface does not change).

Entry filters decide whether to trade a week using only information available at the close
of the previous session (t-1): India VIX, ADX(14) of NIFTY, and scheduled events whose dates
had been published by then. If an indicator is unavailable (e.g. ADX in the first weeks of
data) the week is NOT filtered: it trades as the baseline would.

Early exits close a short leg before expiry using that contract's daily open, high and low,
with conservative fills (M7 pre-registration, section 5):
  stop at S = k x entry fill:        open >= S -> buy at the open (a gap through the stop);
                                     else high >= S -> buy at S
  take-profit at T = (1 - d) x fill: open <= T -> buy at the open; else low <= T -> buy at T
  both touched the same day:         the stop is assumed to have come first
  zero-volume or missing day:        no trigger (the day's range says nothing), counted
Slippage and purchase charges are added by the engine.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True)
class EntryFilter:
    vix_min: float | None = None  # trade only if VIX(t-1) >= vix_min
    vix_max: float | None = None  # trade only if VIX(t-1) < vix_max
    adx_max: float | None = None  # skip if ADX(t-1) > adx_max
    adx_period: int = 14
    skip_scheduled_events: bool = False  # skip if a knowable scheduled event is in the window


@dataclass(frozen=True)
class ExitRule:
    stop_multiple: float | None = None  # buy back a leg at k x its entry fill
    take_profit_decay: float | None = None  # buy back a leg at (1 - d) x its entry fill

    def __post_init__(self) -> None:
        if self.stop_multiple is not None and self.stop_multiple <= 1:
            raise ValueError("stop_multiple must be above 1 (a stop above the entry fill)")
        if self.take_profit_decay is not None and not 0 < self.take_profit_decay < 1:
            raise ValueError("take_profit_decay must be between 0 and 1")


def entry_filter_reason(
    rule: EntryFilter, vix_prev: float, adx_prev: float, knowable_event_count: int
) -> str | None:
    """Why the week is filtered out, or None to trade it. NaN indicator = not filtered."""
    if rule.vix_min is not None and not math.isnan(vix_prev) and vix_prev < rule.vix_min:
        return f"filtered: vix_below_min ({vix_prev:.4f} < {rule.vix_min:g})"
    if rule.vix_max is not None and not math.isnan(vix_prev) and vix_prev >= rule.vix_max:
        return f"filtered: vix_at_or_above_max ({vix_prev:.4f} >= {rule.vix_max:g})"
    if rule.adx_max is not None and not math.isnan(adx_prev) and adx_prev > rule.adx_max:
        return f"filtered: adx_above_max ({adx_prev:.2f} > {rule.adx_max:g})"
    if rule.skip_scheduled_events and knowable_event_count > 0:
        return "filtered: scheduled_event_in_window"
    return None


@dataclass(frozen=True)
class Bar:
    """One contract's prices on one day."""

    day: date
    open: float
    high: float
    low: float
    zero_volume: bool


@dataclass(frozen=True)
class LegExit:
    day: date
    reason: Literal["stop", "take_profit"]
    price: float  # the trigger price, before slippage


def find_exit(rule: ExitRule, entry_fill: float, bars: list[Bar]) -> tuple[LegExit | None, int]:
    """The first day the rule closes this leg (or None), and how many days gave no
    information (zero volume). `bars` are the sessions after entry up to expiry, in order;
    a missing session is simply absent and is counted by the caller."""
    stop = rule.stop_multiple * entry_fill if rule.stop_multiple is not None else None
    target = (
        (1 - rule.take_profit_decay) * entry_fill if rule.take_profit_decay is not None else None
    )
    no_info = 0
    for bar in bars:
        if bar.zero_volume:
            no_info += 1
            continue
        if stop is not None:
            if bar.open >= stop:
                return LegExit(bar.day, "stop", bar.open), no_info
            if bar.high >= stop:
                return LegExit(bar.day, "stop", stop), no_info
        if target is not None:
            if bar.open <= target:
                return LegExit(bar.day, "take_profit", bar.open), no_info
            if bar.low <= target:
                return LegExit(bar.day, "take_profit", target), no_info
    return None, no_info
