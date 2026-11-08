"""Iron condor (M9 plan §2): short strikes and wings scaled by the ATM straddle premium.

On the reference day (the entry day, or the previous session for the C1-R realism check):
  ATM   = listed strike nearest the index close; exact midpoint -> the lower strike (as B0)
  P     = close of the ATM call + close of the ATM put, in points. A reference price only:
          the ATM legs are NOT traded.
  sell  the call nearest ATM + m x P and the put nearest ATM - m x P
  buy   the call nearest (actual short call + w x P) and the put nearest (actual short put - w x P)

Rounding (plan §2.1): "listed" means a row exists for that option type in the reference chain,
whatever its volume; call and put strike lists are searched separately; distances are rounded
to 6 decimal places so floating-point noise can't break a real tie; a tie goes to the lower
strike. The rule never moves to a nearby traded strike: if the nearest strike did not trade,
the engine skips the week (leg_zero_volume), because otherwise volume would shape the trade.

Skip rules raised here (plan §2.3): E1 reference_atm_missing, E2 reference_atm_zero_volume
(a zero-volume close may be stale, and a stale P would move all four strikes), E3
degenerate_strikes. P is never substituted from anywhere else.
"""

from dataclasses import dataclass
from typing import ClassVar

import pandas as pd

from nifty_backtest.strategies.base import Leg, SkipWeek, Strategy
from nifty_backtest.strategies.short_straddle import atm_strike

DISTANCE_DECIMALS = 6


def nearest_listed(strikes: list[float], target: float) -> float:
    """The listed strike nearest `target`; distances rounded first; ties -> lower strike."""
    if not strikes:
        raise SkipWeek("degenerate_strikes: no strikes listed")
    return min(strikes, key=lambda k: (round(abs(k - target), DISTANCE_DECIMALS), k))


@dataclass
class IronCondor(Strategy):
    short_multiple: float = 1.0  # m: short strikes at ATM +/- m x P
    wing_multiple: float = 1.0  # w: long strikes w x P beyond the actual short strikes
    entry_days_before_expiry: int = 3
    lots: int = 1
    name: str = "iron_condor"
    multi_leg: ClassVar[bool] = True
    uses_reference_prices: ClassVar[bool] = True

    def reference(self, chain: pd.DataFrame, spot: float) -> dict[str, float]:
        atm = atm_strike(sorted(set(chain["strike"].tolist())), spot)
        closes = []
        for kind in ("CE", "PE"):
            row = chain[(chain["strike"] == atm) & (chain["option_type"] == kind)]
            if row.empty:
                raise SkipWeek(f"reference_atm_missing: {kind} {atm:g}")
            if bool(row.iloc[0]["zero_volume"]):
                raise SkipWeek(f"reference_atm_zero_volume: {kind} {atm:g}")
            closes.append(float(row.iloc[0]["close"]))
        return {"reference_atm": atm, "reference_premium_points": closes[0] + closes[1]}

    def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
        ref = self.reference(chain, spot)
        atm, premium = ref["reference_atm"], ref["reference_premium_points"]
        calls = sorted(set(chain.loc[chain["option_type"] == "CE", "strike"].tolist()))
        puts = sorted(set(chain.loc[chain["option_type"] == "PE", "strike"].tolist()))
        short_call = nearest_listed(calls, atm + self.short_multiple * premium)
        short_put = nearest_listed(puts, atm - self.short_multiple * premium)
        long_call = nearest_listed(calls, short_call + self.wing_multiple * premium)
        long_put = nearest_listed(puts, short_put - self.wing_multiple * premium)
        if atm in (short_call, short_put) or long_call == short_call or long_put == short_put:
            raise SkipWeek(
                f"degenerate_strikes: {long_put:g}/{short_put:g} PE, "
                f"{short_call:g}/{long_call:g} CE around ATM {atm:g}"
            )
        return [
            Leg("CE", short_call, "sell", self.lots),
            Leg("PE", short_put, "sell", self.lots),
            Leg("CE", long_call, "buy", self.lots),
            Leg("PE", long_put, "buy", self.lots),
        ]
