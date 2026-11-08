"""M9 hand-traced condor trades on the real NSE cache (plan §10). Local only: skipped without data.

The two C1 development trades were picked by code (plan §10, `[trade_trace]`): in expiry order,
the first with no bought leg in the money (NIFTY-2021-10-07) and the first with one
(NIFTY-2021-12-09). Every input below was read by hand from NSE's raw files, not from the
normaliser:
  option rows   data/raw/fo/legacy/2021/fo{04OCT,07OCT,06DEC,09DEC}2021bhav.csv.zip
                (CLOSE, CONTRACTS; on expiry day the SETTLE_PR column holds the index final
                settlement level, spec trap 3)
  NIFTY close   data/raw/index/nifty/2021-10.json and 2021-12.json, EOD_CLOSE_INDEX_VAL
  lot size      reference/lot_sizes_legacy.csv: 50 from 1 Oct 2021 (NSE/FAOP/47854)
The costs are recomputed with the rates written out here (NSE/FATAX/56235, NSE/FA/56129,
SEBI fee regulations, Stamp Act, GST 18%; STT on exercise 0.125% of intrinsic value per
NSE/FATAX/41919), with IPFT in GST's base as the M9 study runs, so the check does not reuse
the engine's cost code.

  4 Oct 2021: NIFTY 17,691.25 -> ATM 17,700; CE 100.30 + PE 92.95 = P 193.25.
    targets 17,893.25 / 17,506.75 -> sell 17,900 CE 26.90, 17,500 PE 31.15;
    wings 18,093.25 / 17,306.75 -> buy 18,100 CE 5.15, 17,300 PE 10.60. Settlement 17,790.35:
    every leg worthless. Net Rs 1,916.8365404458.
  6 Dec 2021: NIFTY 16,912.25 -> ATM 16,900; CE 145.40 + PE 116.15 = P 261.55.
    targets 17,161.55 / 16,638.45 -> sell 17,150 CE 45.85, 16,650 PE 42.20;
    wings 17,411.55 / 16,388.45 -> buy 17,400 CE 12.90, 16,400 PE 14.50. Settlement 17,516.85:
    short call assigned (366.85), long call exercised (116.85). Net Rs -9,677.1059031615.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.research.condor_plan import load_condor_plan, run_config
from nifty_backtest.research.plan import Period

pytestmark = pytest.mark.realdata

PLAN = Path(__file__).resolve().parents[1] / "docs" / "research" / "m9_plan.toml"
# Rates in force in Oct-Dec 2021, written out by hand.
STT_SALE, NSE, IPFT, SEBI, STAMP, GST, STT_EXERCISE = (
    0.0005,  # 0.05% of premium, seller
    0.00053,  # NSE Rs 53 per lakh of premium
    0.000000001,  # IPFT Rs 0.01 per crore
    0.000001,  # SEBI Rs 10 per crore
    0.00003,  # stamp 0.003% of premium, buyer
    0.18,  # GST, here on brokerage + NSE + IPFT + SEBI
    0.00125,  # STT on exercise, holder, on intrinsic value
)
QUANTITY, BROKERAGE, SLIPPAGE = 50, 20.0, 0.5

Leg = tuple[str, str, float, float]  # side, type, strike, raw CLOSE on the entry day


def by_hand(legs: list[Leg], settlement: float) -> dict[str, float]:
    credit_close = credit_fill = value = charges = 0.0
    for side, kind, strike, close in legs:
        sign = 1 if side == "sell" else -1
        fill = close - SLIPPAGE if side == "sell" else close + SLIPPAGE
        premium = fill * QUANTITY
        nse, ipft, sebi = NSE * premium, IPFT * premium, SEBI * premium
        tax = STT_SALE * premium if side == "sell" else STAMP * premium
        charges += BROKERAGE + nse + ipft + sebi + tax + GST * (BROKERAGE + nse + ipft + sebi)
        intrinsic = max(settlement - strike, 0.0) if kind == "CE" else max(strike - settlement, 0.0)
        if intrinsic > 0:
            charges += SEBI * settlement * QUANTITY * (1 + GST)
            if side == "buy":
                charges += STT_EXERCISE * intrinsic * QUANTITY
        credit_close += sign * close
        credit_fill += sign * fill
        value += sign * intrinsic
    return {
        "credit_close": credit_close,
        "credit_fill": credit_fill,
        "value": value,
        "charges": charges,
        "net": (credit_fill - value) * QUANTITY - charges,
    }


def run_c1_week(real_cfg: DataConfig, entry: date, expiry: date):  # type: ignore[no-untyped-def]
    plan = load_condor_plan(PLAN)
    cfg, strategy = run_config(
        plan, plan.variant("C1").settings, Period("trace", entry, expiry), real_cfg, CostConfig()
    )
    return run_backtest(replace(cfg, data=replace(cfg.data, start=entry, end=expiry)), strategy)


@pytest.mark.parametrize(
    ("entry", "expiry", "spot", "atm", "premium", "legs", "settlement", "statuses"),
    [
        (
            date(2021, 10, 4), date(2021, 10, 7), 17691.25, 17700.0, 100.30 + 92.95,
            [("sell", "CE", 17900.0, 26.90), ("sell", "PE", 17500.0, 31.15),
             ("buy", "CE", 18100.0, 5.15), ("buy", "PE", 17300.0, 10.60)],
            17790.35, ["worthless", "worthless", "worthless", "worthless"],
        ),
        (
            date(2021, 12, 6), date(2021, 12, 9), 16912.25, 16900.0, 145.40 + 116.15,
            [("sell", "CE", 17150.0, 45.85), ("sell", "PE", 16650.0, 42.20),
             ("buy", "CE", 17400.0, 12.90), ("buy", "PE", 16400.0, 14.50)],
            17516.85, ["assigned", "worthless", "exercised", "worthless"],
        ),
    ],
)  # fmt: skip
def test_hand_traced_c1_trade(
    real_cfg: DataConfig,
    entry: date,
    expiry: date,
    spot: float,
    atm: float,
    premium: float,
    legs: list[Leg],
    settlement: float,
    statuses: list[str],
) -> None:
    result = run_c1_week(real_cfg, entry, expiry)
    assert result.skipped.empty, result.skipped
    (trade,) = result.trades.to_dict("records")
    assert trade["nifty_close_at_entry"] == spot
    assert trade["reference_atm"] == atm
    assert trade["reference_premium_points"] == pytest.approx(premium)
    assert trade["settlement_level"] == settlement
    assert trade["lot_size"] == 50
    assert result.legs is not None
    got = [
        (r["side"], r["option_type"], r["strike"], r["entry_close"])
        for _, r in result.legs.iterrows()
    ]
    assert got == legs
    assert result.legs["expiry_status"].tolist() == statuses
    hand = by_hand(legs, settlement)
    assert trade["premium_close_points"] == pytest.approx(hand["credit_close"])
    assert trade["premium_fill_points"] == pytest.approx(hand["credit_fill"])
    assert trade["value_at_expiry_points"] == pytest.approx(hand["value"])
    assert trade["charges_rs"] == pytest.approx(hand["charges"], abs=1e-9)
    assert trade["pnl_rs_net"] == pytest.approx(hand["net"], abs=1e-9)
    assert trade["pnl_pct_reference_premium_net"] == pytest.approx(
        100 * hand["net"] / QUANTITY / premium
    )
