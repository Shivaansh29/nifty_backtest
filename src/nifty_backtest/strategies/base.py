"""The one small interface every strategy implements (spec §8).

A strategy only decides WHICH legs to trade, given the option chain and the index level on
the entry day. Everything else (when to enter, fills, costs, marking, settlement) belongs to
the engine, so a new strategy never requires engine changes.

M9 generalised the engine once (plan §9): a strategy with `multi_leg = True` may hold any
number of sold and bought legs, each with a sign (+1 sold, -1 bought) and its own costs. A
strategy with `uses_reference_prices = True` also prices its strikes from reference premiums
(for the iron condor, the ATM straddle), and can raise SkipWeek itself when those are unusable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Literal

import pandas as pd


class SkipWeek(Exception):
    """This week cannot be traded honestly; the message is the logged reason."""


@dataclass(frozen=True)
class Leg:
    option_type: Literal["CE", "PE"]
    strike: float
    side: Literal["sell", "buy"]
    lots: int = 1

    @property
    def sign(self) -> int:
        """+1 for a sold leg (premium received), -1 for a bought leg (premium paid)."""
        return 1 if self.side == "sell" else -1

    @property
    def leg_id(self) -> str:
        """Unique within a position, e.g. "sell-CE-24750"."""
        return f"{self.side}-{self.option_type}-{self.strike:g}"


class Strategy(ABC):
    name: str
    # Entry = this many full trading sessions before the actual expiry (spec §5).
    entry_days_before_expiry: int
    # M9: the engine's signed multi-leg path (bought and sold legs, per-leg files).
    multi_leg: ClassVar[bool] = False
    # M9: legs() prices strikes from reference premiums; see reference().
    uses_reference_prices: ClassVar[bool] = False

    @abstractmethod
    def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
        """Choose the legs to open.

        `chain` holds the entry day's rows for the contracts expiring at the target expiry
        (columns as in the stored option table); `spot` is the index close that day.
        """

    def reference(self, chain: pd.DataFrame, spot: float) -> dict[str, float]:
        """Reference values a multi-leg strategy reports with every trade (none by default)."""
        return {}
