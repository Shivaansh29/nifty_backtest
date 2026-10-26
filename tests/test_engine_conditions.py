"""M7 research conditions in the engine: exits from daily high/low, entry filters on
previous-close information, and the previous-close strike reference.

Built on the hand-built week of test_engine.py (entry Mon 4 Aug 2025, NIFTY 25,020, strike
25,000, lot 75; CE closes 120 / 90 / 60, PE 100 / 110 / 130; settlement 24,900; fills 119.5 and
99.5; entry charges Rs 70.51584595), plus one earlier session, Fri 1 Aug, so that "the
previous close" exists.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nifty_backtest.engine import backtest as engine
from nifty_backtest.engine.backtest import RunConfig, run_backtest
from nifty_backtest.engine.conditions import Bar, EntryFilter, ExitRule, LegExit, find_exit
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.helpers import option_row, write_index, write_scheduled_events
from tests.test_engine import MON, THU, TUE, WED, setup, week

FRI = date(2025, 8, 1)  # the session before the Monday entry: the information day
ENTRY_CHARGES = 70.51584595


def week_with_friday(
    pe_tuesday: tuple[float, float, float] | None = None,
) -> list[dict[str, object]]:
    """The test week plus a Friday row. `pe_tuesday` = (open, high, low) for the ATM put on
    Tuesday (its close stays 110)."""
    rows = week()
    rows.append(option_row(FRI, THU, 75, strike=25000.0, option_type="CE", close=100.0))
    if pe_tuesday:
        for r in rows:
            if (r["trade_date"], r["strike"], r["option_type"]) == (TUE, 25000.0, "PE"):
                r["open"], r["high"], r["low"] = pe_tuesday
    return rows


def run_with(
    cfg: DataConfig, tmp_path: Path, rows: list[dict[str, object]], **changes: object
) -> engine.BacktestResult:
    run = setup(cfg, tmp_path, rows)
    write_index(run.data, {FRI: 25060.0, MON: 25020.0, TUE: 25050.0, WED: 25100.0, THU: 24900.0})
    return run_backtest(replace(run, **changes), ShortStraddle())  # type: ignore[arg-type]


# --- exit rule, on its own -------------------------------------------------------------------

D1, D2, D3 = date(2025, 8, 5), date(2025, 8, 6), date(2025, 8, 7)


def test_a_touch_fills_at_the_stop_and_a_gap_at_the_open() -> None:
    rule = ExitRule(stop_multiple=2.0)  # fill 50 -> stop 100
    touch = [Bar(D1, 60, 101, 55, False)]
    assert find_exit(rule, 50.0, touch)[0] == LegExit(D1, "stop", 100.0)
    gap = [Bar(D1, 120, 130, 110, False)]  # opened above the stop: bought at the open, 120
    assert find_exit(rule, 50.0, gap)[0] == LegExit(D1, "stop", 120.0)


def test_take_profit_fills_at_the_target_or_the_open_below_it() -> None:
    rule = ExitRule(take_profit_decay=0.5)  # fill 50 -> target 25
    assert find_exit(rule, 50.0, [Bar(D1, 40, 45, 24, False)])[0] == LegExit(
        D1, "take_profit", 25.0
    )
    assert find_exit(rule, 50.0, [Bar(D1, 20, 30, 18, False)])[0] == LegExit(
        D1, "take_profit", 20.0
    )


def test_when_both_are_touched_the_same_day_the_stop_is_assumed_first() -> None:
    rule = ExitRule(stop_multiple=2.0, take_profit_decay=0.5)
    both = [Bar(D1, 50, 105, 20, False)]  # high above 100 and low below 25 on one day
    assert find_exit(rule, 50.0, both)[0] == LegExit(D1, "stop", 100.0)


def test_zero_volume_days_cannot_trigger_and_are_counted() -> None:
    rule = ExitRule(stop_multiple=2.0)
    bars = [Bar(D1, 200, 200, 200, True), Bar(D2, 60, 70, 55, False), Bar(D3, 90, 99, 80, False)]
    assert find_exit(rule, 50.0, bars) == (None, 1)


def test_exit_rules_reject_settings_that_make_no_sense() -> None:
    with pytest.raises(ValueError, match="above 1"):
        ExitRule(stop_multiple=0.8)
    with pytest.raises(ValueError, match="between 0 and 1"):
        ExitRule(take_profit_decay=1.2)


# --- exits inside the engine -------------------------------------------------------------------


def test_conditions_that_never_fire_leave_every_number_unchanged(
    cfg: DataConfig, tmp_path: Path
) -> None:
    base = run_with(cfg, tmp_path / "a", week_with_friday())
    quiet = run_with(
        cfg,
        tmp_path / "b",
        week_with_friday(),
        exit_rule=ExitRule(stop_multiple=100.0),
        entry_filter=EntryFilter(vix_min=1.0),
    )
    shared = list(base.trades.columns)
    pd.testing.assert_frame_equal(base.trades, quiet.trades[shared])
    pd.testing.assert_frame_equal(base.marks, quiet.marks[list(base.marks.columns)])
    pd.testing.assert_frame_equal(base.equity, quiet.equity)
    assert quiet.trades.iloc[0]["ce_exit_reason"] == "expiry"


def test_stop_loss_trade_hand_computed(cfg: DataConfig, tmp_path: Path) -> None:
    # Stop at 1.25 x the PE fill: 1.25 x 99.5 = 124.375. On Tue the PE opens at 105 and
    # trades up to 126, so the stop is TOUCHED (not gapped): bought back at 124.375 + 0.5
    # slippage = 124.875. The CE stays open and expires worthless (strike 25,000 > 24,900).
    # Buy-back charges on Rs 124.875 x 75 = 9,365.625 (5 Aug 2025):
    #   brokerage 20, NSE 3.2807784375, IPFT 0.046828125, SEBI 0.009365625,
    #   stamp 0.28096875, GST 0.18 x 23.2901440625 = 4.19222593125   -> 27.81016686875
    # No assignment charge: the PE was bought back, the CE is out of the money.
    # Net = (219 - (0 + 124.875)) x 75 - (70.51584595 + 27.81016686875) = 6,961.04898718125
    # Gross = (220 - (0 + 124.375)) x 75 = 7,171.875; slippage (1 + 0.5) x 75 = 112.5.
    result = run_with(
        cfg,
        tmp_path,
        week_with_friday(pe_tuesday=(105.0, 126.0, 104.0)),
        exit_rule=ExitRule(stop_multiple=1.25),
    )
    t = result.trades.iloc[0]
    assert (t["pe_exit_reason"], t["pe_exit_date"], t["pe_exit_price"]) == ("stop", TUE, 124.375)
    assert (t["ce_exit_reason"], t["ce_exit_price"]) == ("expiry", 0.0)
    assert t["exit_charges_rs"] == pytest.approx(27.81016686875)
    assert t["charges_rs"] == pytest.approx(ENTRY_CHARGES + 27.81016686875)
    assert t["stamp_rs"] == pytest.approx(0.28096875)
    assert t["pnl_rs_gross"] == pytest.approx(7171.875)
    assert t["slippage_rs"] == pytest.approx(112.5)
    assert t["pnl_rs_net"] == pytest.approx(6961.04898718125)
    # Marks: after Tuesday the put is fixed at its exit; the call keeps moving.
    mon, tue, wed, thu = (result.marks.iloc[i] for i in range(4))
    assert [m["date"] for m in (mon, tue, wed, thu)] == [MON, TUE, WED, THU]
    assert tue["pe_mark"] == 124.375
    assert bool(tue["pe_closed"])
    assert not bool(mon["pe_closed"])
    # Tue: (219 - (90 + 124.875)) x 75 - 98.32601281875 = 211.04898718125
    assert tue["mtm_rs_net"] == pytest.approx(211.04898718125)
    # Wed: (219 - (60 + 124.875)) x 75 - 98.32601281875 = 2,461.04898718125
    assert wed["mtm_rs_net"] == pytest.approx(2461.04898718125)
    assert thu["mtm_rs_net"] == pytest.approx(t["pnl_rs_net"])


def test_take_profit_closes_the_call_as_it_decays(cfg: DataConfig, tmp_path: Path) -> None:
    # Target at 50% of the CE fill: 0.5 x 119.5 = 59.75. Wed's CE price is 60 (one price per
    # day in the test rows), just above the target. On expiry day the CE trades at 1.0, below
    # it, so the leg is bought back at Thursday's open, 1.0.
    # At 40% the target is 71.7, and Wed's open of 60 is already below it: bought at 60.
    held = run_with(
        cfg, tmp_path / "a", week_with_friday(), exit_rule=ExitRule(take_profit_decay=0.5)
    )
    t = held.trades.iloc[0]
    assert (t["ce_exit_reason"], t["ce_exit_date"], t["ce_exit_price"]) == ("take_profit", THU, 1.0)
    taken = run_with(
        cfg, tmp_path / "b", week_with_friday(), exit_rule=ExitRule(take_profit_decay=0.4)
    )
    t = taken.trades.iloc[0]
    assert (t["ce_exit_reason"], t["ce_exit_date"], t["ce_exit_price"]) == (
        "take_profit",
        WED,
        60.0,
    )


# --- entry filters ------------------------------------------------------------------------


def test_vix_filter_uses_the_previous_close(cfg: DataConfig, tmp_path: Path) -> None:
    # The test index has VIX 15.0 every day; the decision reads Friday's close.
    traded = run_with(
        cfg, tmp_path / "a", week_with_friday(), entry_filter=EntryFilter(vix_min=15.0)
    )
    t = traded.trades.iloc[0]
    assert (t["info_date"], t["vix_prev_close"]) == (FRI, 15.0)
    skipped = run_with(
        cfg, tmp_path / "b", week_with_friday(), entry_filter=EntryFilter(vix_min=15.5)
    )
    assert skipped.trades.empty
    assert skipped.skipped.iloc[0]["reason"] == "filtered: vix_below_min (15.0000 < 15.5)"
    capped = run_with(
        cfg, tmp_path / "c", week_with_friday(), entry_filter=EntryFilter(vix_max=15.0)
    )
    assert capped.skipped.iloc[0]["reason"].startswith("filtered: vix_at_or_above_max")


@pytest.mark.parametrize(
    ("known", "announced", "original", "filtered"),
    [
        (True, "2025-07-01", "", True),  # published long before: skip the week
        (True, "2025-08-04", "", False),  # published on the entry day, after t-1: not known
        (True, "2025-08-04", "2025-08-05", True),  # originally scheduled inside the window
        (False, "2025-08-06", "", False),  # unscheduled: never knowable
    ],
)
def test_event_filter_counts_only_events_known_by_the_previous_close(
    cfg: DataConfig, tmp_path: Path, known: bool, announced: str, original: str, filtered: bool
) -> None:
    run = setup(cfg, tmp_path, week_with_friday())
    write_scheduled_events(
        run.data.reference_dir, [(WED.isoformat(), "rbi_policy", known, announced, original)]
    )
    write_index(run.data, {FRI: 25060.0, MON: 25020.0, TUE: 25050.0, WED: 25100.0, THU: 24900.0})
    result = run_backtest(
        replace(run, entry_filter=EntryFilter(skip_scheduled_events=True)), ShortStraddle()
    )
    assert result.trades.empty is filtered
    if filtered:
        assert result.skipped.iloc[0]["reason"] == "filtered: scheduled_event_in_window"
    else:
        # The event is still TAGGED on the trade (M3 context); it just was not knowable.
        assert result.trades.iloc[0]["events"] == "rbi_policy@2025-08-06"


def test_adx_filter_reads_the_previous_session_and_skips_strong_trends(
    cfg: DataConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADX itself is tested by hand in test_indicators.py; here, a stand-in series checks the
    # engine reads Friday's value (30) and not Monday's (10).
    stand_in = pd.Series({FRI: 30.0, MON: 10.0, TUE: 10.0, WED: 10.0, THU: 10.0})
    monkeypatch.setattr(engine, "wilder_adx", lambda *args: stand_in)
    result = run_with(cfg, tmp_path, week_with_friday(), entry_filter=EntryFilter(adx_max=25.0))
    assert result.skipped.iloc[0]["reason"] == "filtered: adx_above_max (30.00 > 25)"


def test_missing_adx_does_not_filter(cfg: DataConfig, tmp_path: Path) -> None:
    # Five sessions of data are far too few for ADX(14): the week trades as the baseline.
    result = run_with(cfg, tmp_path, week_with_friday(), entry_filter=EntryFilter(adx_max=25.0))
    assert len(result.trades) == 1
    assert pd.isna(result.trades.iloc[0]["adx_prev"])


# --- strike reference ---------------------------------------------------------------------------


def test_previous_close_picks_the_strike_from_fridays_level(
    cfg: DataConfig, tmp_path: Path
) -> None:
    # Friday closed at 25,060, so the strike nearest it is 25,050 (Monday's 25,020 gives
    # 25,000). The 25,050 legs close at 50 every day in the test week.
    result = run_with(cfg, tmp_path, week_with_friday(), strike_reference="previous_close")
    t = result.trades.iloc[0]
    assert (t["strike"], t["strike_reference_level"]) == (25050.0, 25060.0)
    assert t["nifty_close_at_entry"] == 25020.0  # the notional reference is unchanged
    assert t["premium_close_points"] == 100.0


def test_baseline_config_writes_no_new_columns(cfg: DataConfig, tmp_path: Path) -> None:
    result = run_with(cfg, tmp_path, week_with_friday())
    new = {"ce_exit_reason", "info_date", "strike_reference_level", "exit_charges_rs"}
    assert not new & set(result.trades.columns)
    assert not {"ce_closed", "pe_closed"} & set(result.marks.columns)
    assert RunConfig().strike_reference == "entry_close"
