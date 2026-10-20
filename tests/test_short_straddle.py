"""ATM strike choice for the short straddle (spec §5)."""

import pandas as pd
import pytest

from nifty_backtest.strategies.base import Leg
from nifty_backtest.strategies.short_straddle import ShortStraddle, atm_strike

STRIKES = [23200.0, 23250.0, 23300.0]


@pytest.mark.parametrize(
    ("spot", "expected"),
    [
        (23263.90, 23250.0),  # real 3 Jun 2024 close: 13.90 below vs 36.10 above
        (23280.00, 23300.0),
        (23275.00, 23250.0),  # exact midpoint: the LOWER strike
        (23100.00, 23200.0),  # spot below every strike: nearest is the lowest
    ],
)
def test_atm_strike(spot: float, expected: float) -> None:
    assert atm_strike(STRIKES, spot) == expected


def test_no_strikes_is_an_error() -> None:
    with pytest.raises(ValueError, match="no strikes"):
        atm_strike([], 23000.0)


def test_straddle_sells_one_call_and_one_put_at_the_same_strike() -> None:
    chain = pd.DataFrame({"strike": STRIKES * 2, "option_type": ["CE"] * 3 + ["PE"] * 3})
    legs = ShortStraddle(lots=2).legs(chain, spot=23263.90)
    assert legs == [Leg("CE", 23250.0, "sell", 2), Leg("PE", 23250.0, "sell", 2)]
