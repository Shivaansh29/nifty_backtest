"""M7 indicators and the knowable-event rule, against hand-worked examples."""

import math
from datetime import date

import pandas as pd
import pytest

from nifty_backtest.marketdata.events import Event, knowable_events_between
from nifty_backtest.marketdata.indicators import previous_session, value_before, wilder_adx

DAYS = [date(2025, 1, d) for d in (1, 2, 3, 6, 7)]


def s(values: list[float]) -> pd.Series:
    return pd.Series(values, index=DAYS, dtype=float)


def test_adx_hand_computed_with_period_2() -> None:
    # day  H   L   C  | TR  +DM -DM
    #  0   10  8   9  |  -   -   -
    #  1   11  9  10  |  2   1   0
    #  2   12 10  11  |  2   1   0
    #  3   11  8   9  |  3   0   2   (TR = |8 - 11|; down move 10 - 8 = 2 beats up move -1)
    #  4   12  9  11  |  3   1   0
    # Wilder sums, n = 2. Day 2: TR 4, +DM 2, -DM 0 -> +DI 50, -DI 0, DX 100.
    # Day 3: TR 4 - 2 + 3 = 5, +DM 2 - 1 + 0 = 1, -DM 0 - 0 + 2 = 2 -> +DI 20, -DI 40,
    #        DX = 100 x 20 / 60 = 33.333...; first ADX = mean(100, 33.333) = 66.667.
    # Day 4: TR 5 - 2.5 + 3 = 5.5, +DM 1 - 0.5 + 1 = 1.5, -DM 2 - 1 + 0 = 1
    #        -> +DI 27.2727, -DI 18.1818, DX = 100 x 9.0909 / 45.4545 = 20;
    #        ADX = (66.667 x 1 + 20) / 2 = 43.333.
    adx = wilder_adx(s([10, 11, 12, 11, 12]), s([8, 9, 10, 8, 9]), s([9, 10, 11, 9, 11]), period=2)
    assert all(math.isnan(v) for v in adx.iloc[:3])  # no ADX before day 2n - 1 = 3
    assert adx.iloc[3] == pytest.approx(200 / 3)
    assert adx.iloc[4] == pytest.approx(130 / 3)


def test_adx_is_missing_without_enough_history() -> None:
    s = pd.Series([1.0, 2.0, 3.0], index=DAYS[:3])
    assert wilder_adx(s, s, s, period=14).isna().all()


def test_values_come_from_the_previous_session_only() -> None:
    vix = pd.Series([11.0, 12.0, 13.0, 14.0, 15.0], index=DAYS)
    # Deciding on 6 Jan uses the 3 Jan close, never 6 Jan's own value.
    assert value_before(vix, date(2025, 1, 6)) == 13.0
    assert math.isnan(value_before(vix, date(2025, 1, 1)))
    assert previous_session(DAYS, date(2025, 1, 6)) == date(2025, 1, 3)
    assert previous_session(DAYS, date(2025, 1, 1)) is None


def test_unscheduled_events_are_never_knowable() -> None:
    off_cycle = Event(date(2022, 5, 4), "rbi_policy", "off-cycle", False, date(2022, 5, 4))
    # The 5 May 2022 trade was entered on 29 Apr (information up to 28 Apr).
    assert (
        knowable_events_between([off_cycle], date(2022, 4, 29), date(2022, 5, 5), date(2022, 4, 28))
        == []
    )


def test_an_event_counts_only_once_its_date_was_public() -> None:
    budget = Event(date(2022, 2, 1), "union_budget", "budget", True, date(2022, 1, 27))
    # Information day 28 Jan: the 27 Jan announcement is known -> the event counts.
    assert knowable_events_between(
        [budget], date(2022, 1, 31), date(2022, 2, 3), date(2022, 1, 28)
    ) == [budget]
    # Had the decision been made on 26 Jan, nothing would have been known yet.
    assert (
        knowable_events_between([budget], date(2022, 1, 31), date(2022, 2, 3), date(2022, 1, 26))
        == []
    )


def test_a_rescheduled_meeting_uses_the_date_known_at_the_time() -> None:
    # Feb 2022 MPC: scheduled 7-9 Feb (decision 9 Feb, published 31 Mar 2021), moved to 8-10 Feb
    # on 6 Feb 2022. On 4 Feb only the 9 Feb date was known; it still falls in the
    # 7-10 Feb trade window, so the event counts.
    moved = Event(
        date(2022, 2, 10), "rbi_policy", "rescheduled", True, date(2022, 2, 6), date(2022, 2, 9)
    )
    assert moved.date_known_on(date(2022, 2, 4)) == date(2022, 2, 9)
    assert moved.date_known_on(date(2022, 2, 6)) == date(2022, 2, 10)
    assert knowable_events_between(
        [moved], date(2022, 2, 7), date(2022, 2, 10), date(2022, 2, 4)
    ) == [moved]
    # A window that held only the new date would not have counted it before 6 Feb.
    assert (
        knowable_events_between([moved], date(2022, 2, 9), date(2022, 2, 11), date(2022, 2, 4))
        == []
    )
