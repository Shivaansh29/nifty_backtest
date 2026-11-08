"""The engine's signed multi-leg path (M9 plan §5, §6, §9), on a hand-built week.

Made-up prices, real rate table. Fri 30 May 2025 (previous session), entry Mon 2 Jun, marks
Tue 3 and Wed 4, expiry Thu 5 Jun 2025. Lot 75. NIFTY closes Mon at 24,500 -> ATM 24,500,
P = 130 + 120 = 250. C1: sell 24,750 CE at 40 and 24,250 PE at 45, buy 25,000 CE at 12 and
24,000 PE at 15 (plan §6.4).

Hand calculation (rates on 2 Jun 2025: STT 0.1%, NSE 0.03503%, IPFT 0.0005%, SEBI 0.0001%,
stamp 0.003%, GST 18%; brokerage Rs 20 per order; slippage 0.5 point per leg):
  credit at close  40 + 45 - 12 - 15 = 58 points;  fills 39.5, 44.5 sold, 12.5, 15.5 bought
  filled credit    39.5 + 44.5 - 12.5 - 15.5 = 56 points; wings 250 / 250; max loss 194
  entry charges    GST base without IPFT (default): Rs 104.2870856
                   GST base with IPFT (the M9 study): Rs 104.2946456
                   (per order, e.g. sold 24,750 CE: premium 39.5 x 75 = 2,962.50;
                    STT 2.9625 + NSE 1.03776375 + IPFT 0.0148125 + SEBI 0.0029625 + Rs 20
                    + GST 0.18 x 21.04072625 = 27.80536947 without IPFT)
  settlement 25,100: short call worth 350 (assigned), long call 100 (exercised), puts 0
                   V = 350 - 100 = 250
  expiry charges   assigned: SEBI 0.0001% x 25,100 x 75 = 1.8825, + GST 0.33885
                   exercised: STT 0.125% x 100 x 75 = 9.375, SEBI 1.8825 + GST 0.33885
                   total 13.8177
  net              (56 - 250) x 75 - 104.2946456 - 13.8177 = Rs -14,668.1123456
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig, run_backtest
from nifty_backtest.engine.conditions import EntryFilter, ExitRule
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.strategies.iron_condor import IronCondor
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.helpers import (
    option_row,
    write_events,
    write_index,
    write_processed,
    write_special_sessions,
)

FRI, MON, TUE, WED, THU = (date(2025, 5, 30), *(date(2025, 6, d) for d in (2, 3, 4, 5)))
RATES = Path(__file__).resolve().parents[1] / "reference" / "cost_rates.csv"
ENTRY = 104.2870856  # entry charges, GST base without IPFT
ENTRY_IPFT = 104.2946456  # entry charges, GST base with IPFT
SEBI_N = 0.000001 * 75 * 1.18  # SEBI fee on notional + GST, per index point of settlement
STRIKES = [23900.0 + 50 * i for i in range(25)]  # 23,900 .. 25,100

# Closes of the four C1 legs on Mon, Tue and Wed; every other strike closes at 10.
C1_CLOSES = {
    ("CE", 24750.0): (40.0, 30.0, 20.0),
    ("PE", 24250.0): (45.0, 50.0, 60.0),
    ("CE", 25000.0): (12.0, 8.0, 5.0),
    ("PE", 24000.0): (15.0, 18.0, 20.0),
    # Short strikes of C1-R, chosen from Friday's references (see the look-ahead test).
    ("CE", 24600.0): (30.0, 25.0, 20.0),
    ("PE", 24200.0): (35.0, 40.0, 45.0),
    # Short strikes of C2 (m = 0.75), so every variant of the study test has a credit.
    ("CE", 24700.0): (35.0, 30.0, 25.0),
    ("PE", 24300.0): (40.0, 45.0, 50.0),
}


def condor_week(
    settlement: float = 25100.0,
    *,
    drop: set[tuple[date, str, float]] | None = None,
    zero: set[tuple[date, str, float]] | None = None,
    closes: dict[tuple[str, float], tuple[float, float, float]] | None = None,
    lots: dict[tuple[str, float], int] | None = None,
    friday: bool = True,
) -> list[dict[str, object]]:
    drop, zero, lots = drop or set(), zero or set(), lots or {}
    prices = C1_CLOSES | (closes or {})
    rows = []
    for k in STRIKES:
        for t in ("CE", "PE"):
            mon_tue_wed = prices.get((t, k), (10.0, 10.0, 10.0))
            if k == 24500.0:
                mon_tue_wed = (130.0 if t == "CE" else 120.0, 100.0, 100.0)
            days = dict(zip((MON, TUE, WED), mon_tue_wed, strict=True))
            if friday:
                # Previous session: NIFTY 24,400, ATM 24,400 with P = 110 + 90 = 200.
                days = {FRI: (110.0 if t == "CE" else 90.0) if k == 24400.0 else 10.0} | days
            for day, close in days.items():
                if (day, t, k) in drop:
                    continue
                rows.append(
                    option_row(
                        day,
                        THU,
                        lots.get((t, k), 75),
                        strike=k,
                        option_type=t,
                        close=close,
                        contracts=0 if (day, t, k) in zero else 1000,
                    )
                )
            rows.append(
                option_row(THU, THU, 75, strike=k, option_type=t, close=1.0, settle=settlement)
            )
    return rows


def setup(
    cfg: DataConfig, tmp_path: Path, rows: list[dict[str, object]], *, gst_on_ipft: bool = True
) -> RunConfig:
    ref = tmp_path / "ref"
    write_special_sessions(ref, [])
    write_events(ref, [])
    data = replace(cfg, reference_dir=ref, start=MON, end=THU)
    write_processed(data, rows)
    settlement = float(next(r["settle_price"] for r in rows if r["trade_date"] == THU))  # type: ignore[arg-type]
    write_index(data, {FRI: 24400.0, MON: 24500.0, TUE: 24450.0, WED: 24400.0, THU: settlement})
    return RunConfig(data=data, costs=CostConfig(rates_path=RATES, gst_on_ipft=gst_on_ipft))


def run_c1(cfg: DataConfig, tmp_path: Path, rows: list[dict[str, object]], **kw: bool):  # type: ignore[no-untyped-def]
    return run_backtest(setup(cfg, tmp_path, rows, **kw), IronCondor(short_multiple=1.0))


def test_hand_computed_condor_trade(cfg: DataConfig, tmp_path: Path) -> None:
    result = run_c1(cfg, tmp_path, condor_week(25100.0))
    assert result.skipped.empty
    t = result.trades.iloc[0]
    assert (t["strategy"], t["entry_date"], t["expiry"]) == ("iron_condor", MON, THU)
    assert (t["reference_atm"], t["reference_premium_points"], t["reference_date"]) == (
        24500.0,
        250.0,
        MON,
    )
    assert (t["premium_close_points"], t["premium_fill_points"]) == (58.0, 56.0)
    assert (t["wing_call_points"], t["wing_put_points"], t["max_loss_points"]) == (250, 250, 194)
    assert t["value_at_expiry_points"] == 250.0
    assert t["pnl_points_gross"] == pytest.approx(58 - 250)
    assert t["pnl_rs_gross"] == pytest.approx((58 - 250) * 75)
    assert t["slippage_rs"] == pytest.approx(2 * 75)  # 4 legs x 0.5 point x 75
    assert t["charges_rs"] == pytest.approx(ENTRY_IPFT + 13.8177)
    assert t["stt_rs"] == pytest.approx(2.9625 + 3.3375 + 9.375)  # 2 sales + 1 exercise
    assert t["pnl_rs_net"] == pytest.approx(-14668.1123456)
    assert t["pnl_points_net"] == pytest.approx(-14668.1123456 / 75)
    assert t["pnl_pct_reference_premium_net"] == pytest.approx(-14668.1123456 / 75 / 250 * 100)
    assert t["pnl_pct_max_loss_net"] == pytest.approx(-14668.1123456 / 75 / 194 * 100)
    assert t["pnl_pct_premium_net"] == pytest.approx(-14668.1123456 / 75 / 56 * 100)
    # One-strike straddle columns are blank, never filled with a made-up "main" strike.
    for column in ("strike", "ce_entry_close", "pe_entry_close", "ce_value_at_expiry"):
        assert pd.isna(t[column])


def test_per_leg_records_add_up_to_the_trade(cfg: DataConfig, tmp_path: Path) -> None:
    result = run_c1(cfg, tmp_path, condor_week(25100.0))
    assert result.legs is not None
    legs = result.legs.set_index("leg_id")
    assert list(legs.index) == ["sell-CE-24750", "sell-PE-24250", "buy-CE-25000", "buy-PE-24000"]
    assert legs["entry_fill"].tolist() == [39.5, 44.5, 12.5, 15.5]
    assert legs["intrinsic_at_expiry"].tolist() == [350.0, 0.0, 100.0, 0.0]
    assert legs["expiry_status"].tolist() == ["assigned", "worthless", "exercised", "worthless"]
    assert legs.loc["buy-CE-25000", "stt_rs"] == pytest.approx(9.375)  # exercise, on intrinsic
    assert legs.loc["buy-PE-24000", "stt_rs"] == 0.0  # bought legs pay no STT at entry
    assert legs.loc["buy-CE-25000", "stamp_rs"] == pytest.approx(0.00003 * 12.5 * 75)
    assert legs.loc["sell-CE-24750", "pnl_points_gross"] == pytest.approx(40 - 350)
    assert legs.loc["buy-CE-25000", "pnl_points_gross"] == pytest.approx(100 - 12)
    trade = result.trades.iloc[0]
    for column in ("pnl_rs_gross", "slippage_rs", "charges_rs", "pnl_rs_net", "stt_rs", "gst_rs"):
        assert legs[column].sum() == pytest.approx(trade[column]), column


@pytest.mark.parametrize(
    ("settlement", "value", "expiry_charges"),
    [
        (24600.0, 0.0, 0.0),  # between the short strikes: keep the whole credit
        (24750.0, 0.0, 0.0),  # exactly at the short call: worth 0, not assigned
        (24850.0, 100.0, 24850 * SEBI_N),  # short call assigned
        (25000.0, 250.0, 25000 * SEBI_N),  # exactly at the long call: long leg worth 0
        (25100.0, 250.0, 0.00125 * 100 * 75 + 2 * 25100 * SEBI_N),  # capped by the wing
        (24250.0, 0.0, 0.0),  # put side mirrors the call side
        (24000.0, 250.0, 24000 * SEBI_N),
        (23900.0, 250.0, 0.00125 * 100 * 75 + 2 * 23900 * SEBI_N),
    ],
)
def test_payoff_regions_and_edges(
    cfg: DataConfig, tmp_path: Path, settlement: float, value: float, expiry_charges: float
) -> None:
    t = run_c1(cfg, tmp_path, condor_week(settlement)).trades.iloc[0]
    assert t["value_at_expiry_points"] == pytest.approx(value)
    assert t["pnl_rs_net"] == pytest.approx((56 - value) * 75 - ENTRY_IPFT - expiry_charges)


def test_default_gst_base_differs_only_by_18_percent_of_ipft(
    cfg: DataConfig, tmp_path: Path
) -> None:
    off = run_c1(cfg, tmp_path, condor_week(25100.0), gst_on_ipft=False).trades.iloc[0]
    on = run_c1(cfg, tmp_path, condor_week(25100.0), gst_on_ipft=True).trades.iloc[0]
    assert off["charges_rs"] == pytest.approx(ENTRY + 13.8177)
    assert on["gst_rs"] - off["gst_rs"] == pytest.approx(0.18 * off["ipft_rs"])
    for column in ("brokerage_rs", "stt_rs", "exchange_rs", "ipft_rs", "sebi_rs", "stamp_rs"):
        assert on[column] == off[column]


def test_daily_marks_leg_marks_and_equity(cfg: DataConfig, tmp_path: Path) -> None:
    result = run_c1(cfg, tmp_path, condor_week(25100.0))
    marks = result.marks.set_index("date")
    # Signed position value: sold legs count +, bought legs -.
    assert marks["position_value_points"].tolist() == [58.0, 54.0, 55.0, 250.0]
    assert marks.loc[TUE, "mtm_rs_net"] == pytest.approx((56 - 54) * 75 - ENTRY_IPFT)
    assert marks.loc[THU, "mtm_rs_net"] == pytest.approx(-14668.1123456)
    assert marks["ce_mark"].isna().all()
    assert marks["pe_mark"].isna().all()
    assert result.leg_marks is not None
    lm = result.leg_marks.set_index(["leg_id", "date"])
    assert lm.loc[("buy-PE-24000", WED), "close"] == 20.0
    assert lm.loc[("sell-CE-24750", THU), "close"] == 350.0  # expiry day: settlement value
    assert len(result.leg_marks) == 4 * 4
    equity = result.equity.set_index("date")["equity_rs"]
    assert equity[MON] == pytest.approx(500_000 + (56 - 58) * 75 - ENTRY_IPFT)
    assert equity[THU] == pytest.approx(500_000 - 14668.1123456)


def test_stale_and_missing_holding_marks_keep_the_trade(cfg: DataConfig, tmp_path: Path) -> None:
    rows = condor_week(25100.0, zero={(TUE, "CE", 24750.0)}, drop={(WED, "PE", 24000.0)})
    result = run_c1(cfg, tmp_path, rows)
    assert len(result.trades) == 1  # holding-period liquidity never removes a week
    marks = result.marks.set_index("date")
    assert bool(marks.loc[TUE, "stale_mark"])
    assert not bool(marks.loc[TUE, "missing_mark"])
    assert bool(marks.loc[WED, "missing_mark"])
    assert pd.isna(marks.loc[WED, "position_value_points"])
    assert pd.isna(marks.loc[WED, "mtm_rs_net"])  # never filled or carried forward
    assert pd.isna(result.equity.set_index("date").loc[WED, "equity_rs"])
    t = result.trades.iloc[0]
    assert (t["stale_marks"], t["missing_marks"], t["legs_stale_days"]) == (1, 1, 1)
    assert result.leg_marks is not None
    lm = result.leg_marks.set_index(["leg_id", "date"])
    assert bool(lm.loc[("sell-CE-24750", TUE), "stale"])
    assert bool(lm.loc[("buy-PE-24000", WED), "missing"])
    assert pd.isna(lm.loc[("buy-PE-24000", WED), "close"])


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"zero": {(MON, "CE", 24750.0)}}, "leg_zero_volume"),  # E5
        ({"lots": {("CE", 25000.0): 50}}, "legs_have_different_quantities"),  # E6
        # E8: credit at the close 40 + 45 - 40 - 45 = 0.
        ({"closes": {("CE", 25000.0): (40.0, 8.0, 5.0), ("PE", 24000.0): (45.0, 18.0, 20.0)}},
         "no_positive_credit"),
        # E8: credit 200 + 200 - 12 - 15 = 373 > widest wing 250: no risk left to measure.
        ({"closes": {("CE", 24750.0): (200.0, 1.0, 1.0), ("PE", 24250.0): (200.0, 1.0, 1.0)}},
         "no_defined_risk"),
    ],
)  # fmt: skip
def test_entry_skip_rules_in_order(
    cfg: DataConfig, tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    result = run_c1(cfg, tmp_path, condor_week(25100.0, **change))  # type: ignore[arg-type]
    assert result.trades.empty
    assert result.skipped["reason"].iloc[0].split(":")[0] == reason


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"drop": {(MON, "PE", 24000.0)}}, "leg_missing"),  # E4
        # E4 is checked on every leg before E5 on any leg.
        ({"drop": {(MON, "PE", 24000.0)}, "zero": {(MON, "CE", 24600.0)}}, "leg_missing"),
    ],
)
def test_e4_leg_missing_applies_when_strikes_come_from_the_previous_session(
    cfg: DataConfig, tmp_path: Path, change: dict[str, object], reason: str
) -> None:
    # With same-close strikes a leg is chosen from the entry chain itself, so it always exists;
    # E4 matters for C1-R, whose strikes are chosen from Friday's chain.
    run = setup(cfg, tmp_path, condor_week(25100.0, **change))  # type: ignore[arg-type]
    result = run_backtest(replace(run, strike_reference="previous_close"), IronCondor())
    assert result.trades.empty
    assert result.skipped["reason"].iloc[0].split(":")[0] == reason


def test_e6_unknown_lot_size(cfg: DataConfig, tmp_path: Path) -> None:
    rows = condor_week(25100.0)
    for r in rows:
        if (r["trade_date"], r["option_type"], r["strike"]) == (MON, "PE", 24250.0):
            r["lot_size"], r["lot_size_source"] = None, None
    result = run_c1(cfg, tmp_path, rows)
    assert result.skipped["reason"].iloc[0].startswith("lot_size_unknown")


def test_e1_and_e2_are_logged_by_the_engine(cfg: DataConfig, tmp_path: Path) -> None:
    rows = condor_week(25100.0, zero={(MON, "PE", 24500.0)})
    result = run_c1(cfg, tmp_path, rows)
    assert result.skipped["reason"].iloc[0].startswith("reference_atm_zero_volume")


def test_unequal_wings_use_the_wider_one(cfg: DataConfig, tmp_path: Path) -> None:
    # No 25,000 CE on Mon: the long call is 24,950 (close 10), so wings are 200 and 250.
    t = run_c1(cfg, tmp_path, condor_week(25100.0, drop={(MON, "CE", 25000.0)})).trades.iloc[0]
    assert (t["wing_call_points"], t["wing_put_points"]) == (200.0, 250.0)
    assert t["premium_fill_points"] == 39.5 + 44.5 - 10.5 - 15.5  # 58
    assert t["max_loss_points"] == pytest.approx(250 - 58)


def test_previous_close_reference_has_no_look_ahead(cfg: DataConfig, tmp_path: Path) -> None:
    """C1-R: ATM, P and strikes from Fri (NIFTY 24,400, P = 200): sell 24,600 CE and 24,200
    PE, buy 24,800 CE and 24,000 PE. Changing every entry-day close must not move a strike."""
    run = replace(setup(cfg, tmp_path, condor_week(25100.0)), strike_reference="previous_close")
    t = run_backtest(run, IronCondor()).trades.iloc[0]
    assert (t["reference_date"], t["reference_atm"], t["reference_premium_points"]) == (
        FRI,
        24400.0,
        200.0,
    )
    legs = run_backtest(run, IronCondor()).legs
    assert legs is not None
    assert legs["strike"].tolist() == [24600.0, 24200.0, 24800.0, 24000.0]
    assert legs["entry_close"].tolist() == [30.0, 35.0, 10.0, 15.0]  # fills use Mon's closes

    doubled = {key: (2 * v[0], v[1], v[2]) for key, v in C1_CLOSES.items()}
    doubled |= {("CE", k): (77.0, 10.0, 10.0) for k in STRIKES if ("CE", k) not in doubled}
    mutated = replace(
        setup(cfg, tmp_path / "m", condor_week(25100.0, closes=doubled)),
        strike_reference="previous_close",
    )
    mutated_legs = run_backtest(mutated, IronCondor()).legs
    assert mutated_legs is not None
    assert mutated_legs["strike"].tolist() == legs["strike"].tolist()
    assert mutated_legs["entry_close"].tolist() != legs["entry_close"].tolist()


def test_previous_close_reference_chain_missing(cfg: DataConfig, tmp_path: Path) -> None:
    # Friday is still a session (a BANKNIFTY row), but has no NIFTY rows for this expiry.
    other = option_row(FRI, THU, 30, strike=50000.0, option_type="CE", close=100.0)
    other["underlying"] = "BANKNIFTY"
    rows = [*condor_week(25100.0, friday=False), other]
    run = replace(setup(cfg, tmp_path, rows), strike_reference="previous_close")
    reasons = run_backtest(run, IronCondor()).skipped["reason"].tolist()
    assert [r.split(":")[0] for r in reasons] == ["reference_chain_missing"]


def test_exit_rules_and_entry_filters_are_refused_with_bought_legs(
    cfg: DataConfig, tmp_path: Path
) -> None:
    run = setup(cfg, tmp_path, condor_week())
    with pytest.raises(ValueError, match="exit rule"):
        run_backtest(replace(run, exit_rule=ExitRule(stop_multiple=2.0)), IronCondor())
    with pytest.raises(ValueError, match="entry filter"):
        run_backtest(replace(run, entry_filter=EntryFilter(vix_min=10.0)), IronCondor())


def test_per_leg_files_are_written_only_for_multi_leg_runs(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, condor_week())
    condor = save_run(run_backtest(run, IronCondor()), run, IronCondor(), tmp_path / "runs")
    assert (condor / "legs.csv").exists()
    assert (condor / "leg_marks.csv").exists()
    straddle_result = run_backtest(run, ShortStraddle())
    assert straddle_result.legs is None
    assert straddle_result.leg_marks is None
    straddle = save_run(straddle_result, run, ShortStraddle(), tmp_path / "runs2")
    assert not (straddle / "legs.csv").exists()


def test_e7_settlement_level_missing(cfg: DataConfig, tmp_path: Path) -> None:
    # Expiring contracts that disagree on the settle column give no usable settlement level.
    rows = condor_week(25100.0)
    thursday = [r for r in rows if r["trade_date"] == THU]
    thursday[0]["settle_price"] = 25099.0
    result = run_c1(cfg, tmp_path, rows)
    assert result.trades.empty
    assert result.skipped["reason"].iloc[0] == "settlement_level_missing"
