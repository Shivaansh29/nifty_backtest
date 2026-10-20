"""The one small interface every strategy implements (spec §8).

A strategy only decides WHICH legs to trade, given the option chain and the index level on
the entry day. Everything else (when to enter, fills, costs, marking, settlement) belongs to
the engine, so a new strategy never requires engine changes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class Leg:
    option_type: Literal["CE", "PE"]
    strike: float
    side: Literal["sell", "buy"]
    lots: int = 1


class Strategy(ABC):
    name: str
    # Entry = this many full trading sessions before the actual expiry (spec §5).
    entry_days_before_expiry: int

    @abstractmethod
    def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
        """Choose the legs to open.

        `chain` holds the entry day's rows for the contracts expiring at the target expiry
        (columns as in the stored option table); `spot` is the index close that day.
        """
