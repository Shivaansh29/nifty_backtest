"""Short straddle (spec §5): sell one ATM call and one ATM put of the nearest expiry."""

from dataclasses import dataclass

import pandas as pd

from nifty_backtest.strategies.base import Leg, Strategy


def atm_strike(strikes: list[float], spot: float) -> float:
    """The strike nearest to `spot`; at an exact midpoint, the LOWER strike (spec §5)."""
    if not strikes:
        raise ValueError("no strikes listed")
    # Sorting by (distance, strike) makes the tie-break explicit: equal distance -> lower strike.
    return min(strikes, key=lambda k: (abs(k - spot), k))


@dataclass
class ShortStraddle(Strategy):
    entry_days_before_expiry: int = 3
    lots: int = 1
    name: str = "short_straddle"

    def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
        strike = atm_strike(sorted(set(chain["strike"].tolist())), spot)
        return [
            Leg("CE", strike, "sell", self.lots),
            Leg("PE", strike, "sell", self.lots),
        ]
