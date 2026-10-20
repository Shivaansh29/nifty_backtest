"""Engine tests on a hand-built week (made-up prices, real rate table).

The week of Mon 4 - Thu 7 Aug 2025: one NIFTY expiry on Thu, entry 3 sessions earlier (Mon).
Mon close 25,020 -> ATM strike 25,000. Lot 75.

Worked by hand (rates in force on 4 Aug 2025: STT 0.1%, NSE 0.03503%, IPFT 0.0005%,
SEBI 0.0001%, GST 18%; brokerage Rs 20 per order; slippage 0.5 point per leg):
  entry closes  CE 120.00 + PE 100.00 = 220.00 points; fills 119.50 + 99.50 = 219.00
  premium       CE 119.50 x 75 = 8,962.50 ; PE 99.50 x 75 = 7,462.50 ; total 16,425.00
  entry charges STT 16.425 + NSE 5.7536775 + IPFT 0.082125 + SEBI 0.016425
                + brokerage 40 + GST 0.18 x 45.7701025 = 8.23861845      = 70.51584595
  expiry        settlement 24,900: CE worth 0, PE worth 100.00 (assigned)
  expiry charges SEBI on notional 24,900 x 75 = 1.8675, GST 0.33615       =  2.20365
  gross P&L     (220 - 100) points = 120.00 -> x 75 = Rs 9,000.00
  net P&L       (219 - 100) x 75 - (70.51584595 + 2.20365) = Rs 8,852.28050405
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig, run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.helpers import (
    option_row,
    write_events,
    write_index,
    write_processed,
    write_special_sessions,
)

MON, TUE, WED, THU = date(2025, 8, 4), date(2025, 8, 5), date(2025, 8, 6), date(2025, 8, 7)
FRI, NEXT_THU = date(2025, 8, 8), date(2025, 8, 14)
RATES = Path(__file__).resolve().parents[1] / "reference" / "cost_rates.csv"


def week(
    *, ce_contracts: int = 1000, with_pe: bool = True, lot: int | None = 75
) -> list[dict[str, object]]:
    rows = []
    for k in (24950.0, 25000.0, 25050.0):
        for t in ("CE", "PE"):
            if t == "PE" and k == 25000.0 and not with_pe:
                continue
            contracts = ce_contracts if (t, k) == ("CE", 25000.0) else 1000
            closes = (
                {MON: 120.0, TUE: 90.0, WED: 60.0}
                if t == "CE"
                else {MON: 100.0, TUE: 110.0, WED: 130.0}
            )
            if k != 25000.0:
                closes = {d: 50.0 for d in closes}
            for day, close in closes.items():
                rows.append(
                    option_row(
                        day,
                        THU,
                        lot,
                        strike=k,
                        option_type=t,
                        close=close,
                        contracts=contracts if day == MON else 1000,
                    )
                )
            rows.append(
                option_row(THU, THU, lot, strike=k, option_type=t, close=1.0, settle=24900.0)
            )
    return rows


def setup(cfg: DataConfig, tmp_path: Path, rows: list[dict[str, object]]) -> RunConfig:
    ref = tmp_path / "ref"
    write_special_sessions(ref, [])
    # An RBI decision on the entry day (already in the entry prices) and one mid-trade.
    write_events(ref, [(MON.isoformat(), "rbi_policy"), (WED.isoformat(), "rbi_policy")])
    data = replace(cfg, reference_dir=ref, start=MON, end=THU)
    write_processed(data, rows)
    write_index(data, {MON: 25020.0, TUE: 25050.0, WED: 25100.0, THU: 24900.0})
    return RunConfig(data=data, costs=CostConfig(rates_path=RATES))


def test_hand_computed_trade(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week())
    result = run_backtest(run, ShortStraddle())
    assert result.skipped.empty
    trade = result.trades.iloc[0]
    assert (trade["entry_date"], trade["expiry"], trade["strike"]) == (MON, THU, 25000.0)
    assert (trade["premium_close_points"], trade["premium_fill_points"]) == (220.0, 219.0)
    assert (trade["quantity"], trade["settlement_level"]) == (75, 24900.0)
    assert (trade["ce_value_at_expiry"], trade["pe_value_at_expiry"]) == (0.0, 100.0)
    assert trade["pnl_points_gross"] == pytest.approx(120.0)
    assert trade["pnl_rs_gross"] == pytest.approx(9000.0)
    assert trade["slippage_rs"] == pytest.approx(75.0)  # 1 point (2 legs x 0.5) x 75
    assert trade["charges_rs"] == pytest.approx(70.51584595 + 2.20365)
    assert trade["pnl_rs_net"] == pytest.approx(8852.28050405)
    assert trade["pnl_points_net"] == pytest.approx(8852.28050405 / 75)
    assert trade["pnl_pct_premium_gross"] == pytest.approx(120.0 / 220.0 * 100)
    # Context: entry-day event excluded (already priced in), mid-trade event included.
    assert trade["events"] == "rbi_policy@2025-08-06"
    assert trade["nifty_move_pct"] == pytest.approx((24900 / 25020 - 1) * 100)
    assert trade["vix_at_entry"] == 15.0


def test_daily_marks_and_equity_curve(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week())
    result = run_backtest(run, ShortStraddle())
    marks = result.marks.set_index("date")
    entry_charges = 70.51584595
    # Position value = CE + PE close; seller's mark = (fill premium - value) x 75 - charges.
    assert marks["position_value_points"].tolist() == [220.0, 200.0, 190.0, 100.0]
    assert marks.loc[MON]["mtm_rs_net"] == pytest.approx((219 - 220) * 75 - entry_charges)
    assert marks.loc[TUE]["mtm_rs_net"] == pytest.approx((219 - 200) * 75 - entry_charges)
    assert marks.loc[WED]["mtm_rs_net"] == pytest.approx((219 - 190) * 75 - entry_charges)
    equity = result.equity.set_index("date")["equity_rs"]
    assert equity[MON] == pytest.approx(500_000 - 75 - entry_charges)
    assert equity[WED] == pytest.approx(500_000 + 29 * 75 - entry_charges)
    assert equity[THU] == pytest.approx(500_000 + 8852.28050405)  # realised on expiry day


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        (week(ce_contracts=0), "leg_zero_volume: CE 25000"),  # stale close is never a fill
        (week(with_pe=False), "leg_missing: PE 25000"),
        (week(lot=None), "lot_size_unknown: CE 25000"),  # spec: skip, never guess the lot
    ],
)
def test_untradeable_weeks_are_skipped_with_a_reason(
    cfg: DataConfig, tmp_path: Path, rows: list[dict[str, object]], reason: str
) -> None:
    result = run_backtest(setup(cfg, tmp_path, rows), ShortStraddle())
    assert result.trades.empty
    assert result.skipped["reason"].tolist() == [reason]


def test_redated_contract_is_traded_and_marked_through_the_relabel(
    cfg: DataConfig, tmp_path: Path
) -> None:
    # Like 29 -> 28 Jun 2023: contracts printed as expiring Thu on Mon and Tue, re-dated to
    # Wed on Wed, and settled Wed. Another contract trades Thu/Fri, so Thu passes without them.
    rows = []
    for t, closes in (("CE", (100.0, 80.0)), ("PE", (90.0, 70.0))):
        rows.append(option_row(MON, THU, 75, strike=25000.0, option_type=t, close=closes[0]))
        rows.append(option_row(TUE, THU, 75, strike=25000.0, option_type=t, close=closes[1]))
        rows.append(option_row(WED, WED, 75, strike=25000.0, option_type=t, settle=25040.0))
    rows += [option_row(d, NEXT_THU, 75) for d in (MON, TUE, WED, THU, FRI)]
    run = setup(cfg, tmp_path, rows)
    run = replace(run, data=replace(run.data, end=FRI))
    write_index(run.data, {MON: 24990.0, TUE: 25000.0, WED: 25040.0, THU: 25000.0, FRI: 25000.0})
    result = run_backtest(run, ShortStraddle(entry_days_before_expiry=2))
    trade = result.trades.set_index("expiry").loc[WED]
    assert (trade["entry_date"], trade["stated_expiry_on_entry"], trade["relabelled"]) == (
        MON,
        THU,
        True,
    )
    assert trade["value_at_expiry_points"] == pytest.approx(40.0)  # CE: 25,040 - 25,000
    marks = result.marks[result.marks["expiry"] == WED].set_index("date")
    assert marks.loc[TUE]["position_value_points"] == 150.0  # marked under its old label
    assert not marks["missing_mark"].any()


def test_saved_run_has_config_manifest_and_logs(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week())
    result = run_backtest(run, ShortStraddle())
    folder = save_run(result, run, ShortStraddle(), runs_dir=tmp_path / "runs")
    names = {p.name for p in folder.iterdir()}
    assert names == {
        "config.json",
        "manifest.json",
        "trades.csv",
        "marks.csv",
        "equity.csv",
        "skipped.csv",
    }
    manifest = (folder / "manifest.json").read_text()
    assert '"trading_day_count": 4' in manifest
    assert '"option_data_sha256"' in manifest
    assert '"brokerage_per_order_rs": 20.0' in (folder / "config.json").read_text()
