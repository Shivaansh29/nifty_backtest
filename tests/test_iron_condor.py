"""Iron condor strike selection (M9 plan §2, §2.1-§2.3), on hand-built option chains.

Worked example (plan §2.4): NIFTY 24,500, ATM 24,500, P = CE 130 + PE 120 = 250 points.
C1 (m = 1): sell 24,750 CE and 24,250 PE; buy 25,000 CE and 24,000 PE.
"""

import pandas as pd
import pytest

from nifty_backtest.strategies.base import Leg, SkipWeek
from nifty_backtest.strategies.iron_condor import IronCondor


def chain(
    strikes: list[float] | None = None,
    *,
    drop: tuple[tuple[str, float], ...] = (),
    zero: tuple[tuple[str, float], ...] = (),
    atm_ce: float = 130.0,
    atm_pe: float = 120.0,
) -> pd.DataFrame:
    """Rows for both option types at every strike; ATM 24,500 carries the reference closes."""
    rows = []
    for k in strikes or [23900.0 + 50 * i for i in range(25)]:  # 23,900 .. 25,100
        for t in ("CE", "PE"):
            if (t, k) in drop:
                continue
            close = (atm_ce if t == "CE" else atm_pe) if k == 24500.0 else 10.0
            rows.append(
                {"strike": k, "option_type": t, "close": close, "zero_volume": (t, k) in zero}
            )
    return pd.DataFrame(rows)


def test_c1_strikes_from_the_worked_example() -> None:
    legs = IronCondor(short_multiple=1.0).legs(chain(), 24500.0)
    assert legs == [
        Leg("CE", 24750.0, "sell"),
        Leg("PE", 24250.0, "sell"),
        Leg("CE", 25000.0, "buy"),
        Leg("PE", 24000.0, "buy"),
    ]


def test_reference_premium_and_atm_are_reported() -> None:
    ref = IronCondor().reference(chain(), 24510.0)
    assert ref == {"reference_atm": 24500.0, "reference_premium_points": 250.0}


@pytest.mark.parametrize(
    ("multiple", "short_call", "short_put", "long_call", "long_put"),
    [
        # C2: 0.75 x 250 = 187.5 -> targets 24,687.5 / 24,312.5 -> nearest 24,700 / 24,300.
        (0.75, 24700.0, 24300.0, 24950.0, 24050.0),
        # C3: 1.25 x 250 = 312.5 -> 24,812.5 / 24,187.5 -> 24,800 / 24,200.
        (1.25, 24800.0, 24200.0, 25050.0, 23950.0),
    ],
)
def test_c2_and_c3_round_to_the_nearest_listed_strike(
    multiple: float, short_call: float, short_put: float, long_call: float, long_put: float
) -> None:
    legs = IronCondor(short_multiple=multiple).legs(chain(), 24500.0)
    assert [leg.strike for leg in legs] == [short_call, short_put, long_call, long_put]


def test_exact_midpoint_goes_to_the_lower_strike_on_both_sides() -> None:
    # P = 225: targets 24,725 (between 24,700 and 24,750) and 24,275 (24,250 / 24,300).
    legs = IronCondor().legs(chain(atm_ce=125.0, atm_pe=100.0), 24500.0)
    assert legs[0].strike == 24700.0  # call: lower of the two
    assert legs[1].strike == 24250.0  # put: lower of the two, not the one nearer ATM


def test_floating_point_noise_cannot_break_a_real_tie() -> None:
    # P = 225.000000001: unrounded, 24,750 would look nearer by 2e-9 points. Rounded to 6
    # decimals both distances are 25, a tie, so the lower strike wins as the rule says.
    legs = IronCondor().legs(chain(atm_ce=125.0, atm_pe=100.000000001), 24500.0)
    assert legs[0].strike == 24700.0


def test_call_and_put_strike_lists_are_searched_separately() -> None:
    # 24,750 exists only as a put: the short call must come from the CE list (24,800).
    legs = IronCondor().legs(chain(drop=(("CE", 24750.0),)), 24500.0)
    assert legs[0] == Leg("CE", 24700.0, "sell")  # 24,700 and 24,800 tie -> lower


def test_wing_is_measured_from_the_actual_short_strike_and_may_be_unequal() -> None:
    # Remove 25,000 CE: the long call target 25,000 rounds to 24,950 (tie with 25,050 -> lower).
    legs = IronCondor().legs(chain(drop=(("CE", 25000.0),)), 24500.0)
    assert legs[2] == Leg("CE", 24950.0, "buy")
    assert legs[3] == Leg("PE", 24000.0, "buy")  # put wing unchanged: wings now 200 and 250


def test_zero_volume_strike_is_kept_listed_rule_never_hunts_for_liquidity() -> None:
    # A zero-volume 24,750 CE is still the nearest listed strike; the engine skips the week.
    legs = IronCondor().legs(chain(zero=(("CE", 24750.0),)), 24500.0)
    assert legs[0] == Leg("CE", 24750.0, "sell")


def test_e1_reference_atm_missing() -> None:
    with pytest.raises(SkipWeek, match=r"^reference_atm_missing"):
        IronCondor().legs(chain(drop=(("PE", 24500.0),)), 24500.0)


def test_e2_reference_atm_zero_volume() -> None:
    with pytest.raises(SkipWeek, match=r"^reference_atm_zero_volume"):
        IronCondor().legs(chain(zero=(("CE", 24500.0),)), 24500.0)


def test_e3_degenerate_strikes() -> None:
    # m = 0.05 -> 12.5 points from ATM: the nearest call is the ATM strike itself.
    with pytest.raises(SkipWeek, match=r"^degenerate_strikes"):
        IronCondor(short_multiple=0.05).legs(chain(), 24500.0)


def test_e3_long_strike_equal_to_short_strike() -> None:
    # No call strikes above 24,750: the long call rounds back onto the short call.
    strikes = [23900.0 + 50 * i for i in range(18)]  # up to 24,750
    with pytest.raises(SkipWeek, match=r"^degenerate_strikes"):
        IronCondor().legs(chain(strikes), 24500.0)


def test_strategy_declares_signed_legs_and_reference_prices() -> None:
    condor = IronCondor()
    assert condor.multi_leg is True
    assert condor.uses_reference_prices is True
    assert condor.name == "iron_condor"
