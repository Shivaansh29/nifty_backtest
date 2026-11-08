"""Architecture check (M9 review): a future bought-leg strategy runs through the multi-leg path
with no engine change. The strategy is defined HERE, in the test, not shipped: adding real
strategies (debit spreads, strangles) is later work.

A bull call spread on the hand-built week of test_engine_multileg (entry Mon 2 Jun 2025, NIFTY
24,500, lot 75, settlement 25,100): buy the ATM 24,500 CE at 130, sell the 24,600 CE at 30.
  debit at the close  130 - 30 = 100 points; filled 130.5 bought, 29.5 sold -> 101 points paid
  at expiry           long 24,500 CE worth 600 (exercised), short 24,600 CE worth 500 (assigned)
                      signed value V = -600 + 500 = -100
  P&L per unit        filled credit -101 - V(-100) = -1 point, before charges
  maximum loss        the debit, 101 points (both calls in the money: the spread is worth 100)
Charges (rates on 2 Jun 2025; GST without IPFT, the engine default):
  buy  24,500 CE premium 130.5 x 75 = 9,787.50: Rs 20 + NSE 3.42856125 + IPFT 0.0489375
       + SEBI 0.0097875 + stamp 0.293625 + GST 0.18 x 23.43834875
  sell 24,600 CE premium 29.5 x 75 = 2,212.50: Rs 20 + STT 2.2125 + NSE 0.77503875
       + IPFT 0.0110625 + SEBI 0.0022125 + GST 0.18 x 20.77725125
  expiry: exercised STT 0.125% x 600 x 75 = 56.25; SEBI on 25,100 x 75 for each leg + GST
"""

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pandas as pd
import pytest

from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.strategies.base import Leg, Strategy
from nifty_backtest.strategies.short_straddle import atm_strike
from tests.test_engine_multileg import condor_week, setup


@dataclass
class BullCallSpread(Strategy):
    """Buy the ATM call, sell the call `width` points above it: a net DEBIT."""

    width: float = 100.0
    entry_days_before_expiry: int = 3
    lots: int = 1
    name: str = "bull_call_spread"
    multi_leg: ClassVar[bool] = True

    def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
        atm = atm_strike(sorted(set(chain["strike"].tolist())), spot)
        return [Leg("CE", atm, "buy", self.lots), Leg("CE", atm + self.width, "sell", self.lots)]


SEBI_EXPIRY = 0.000001 * 25100 * 75 * 1.18  # per in-the-money leg
BUY = 20 + 3.42856125 + 0.0489375 + 0.0097875 + 0.293625 + 0.18 * 23.43834875
SELL = 20 + 2.2125 + 0.77503875 + 0.0110625 + 0.0022125 + 0.18 * 20.77725125
CHARGES = BUY + SELL + 56.25 + 2 * SEBI_EXPIRY


def test_a_debit_spread_runs_through_the_multi_leg_path(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, condor_week(25100.0), gst_on_ipft=False)
    result = run_backtest(run, BullCallSpread())
    assert result.skipped.empty, result.skipped
    t = result.trades.iloc[0]
    assert t["strategy"] == "bull_call_spread"
    assert (t["premium_close_points"], t["premium_fill_points"]) == (-100.0, -101.0)  # debits
    assert t["value_at_expiry_points"] == pytest.approx(-100.0)
    assert t["max_loss_points"] == pytest.approx(101.0)  # the debit, not width - credit
    assert t["charges_rs"] == pytest.approx(CHARGES)
    assert t["pnl_rs_net"] == pytest.approx(-1 * 75 - CHARGES)
    assert t["pnl_pct_max_loss_net"] == pytest.approx(100 * (-75 - CHARGES) / 75 / 101)
    # No reference premium is declared, so R_P is blank: nothing is made up.
    assert pd.isna(t["reference_premium_points"])
    assert pd.isna(t["pnl_pct_reference_premium_net"])
    assert result.legs is not None
    assert result.legs["expiry_status"].tolist() == ["exercised", "assigned"]
    assert result.legs["pnl_rs_net"].sum() == pytest.approx(t["pnl_rs_net"])


def test_an_unbounded_position_has_no_maximum_loss(cfg: DataConfig, tmp_path: Path) -> None:
    """A position whose loss has no floor (here: buy the 24,500 PE, sell the 24,600 CE, so a
    rally loses without limit) gets a blank maximum loss rather than a number, and is not
    skipped for it."""

    @dataclass
    class RiskReversal(BullCallSpread):
        name: str = "risk_reversal"

        def legs(self, chain: pd.DataFrame, spot: float) -> list[Leg]:
            return [Leg("PE", 24500.0, "buy", 1), Leg("CE", 24600.0, "sell", 1)]

    run = setup(cfg, tmp_path, condor_week(24550.0), gst_on_ipft=False)
    result = run_backtest(run, RiskReversal())
    assert result.skipped.empty, result.skipped
    assert pd.isna(result.trades.iloc[0]["max_loss_points"])
    assert pd.isna(result.trades.iloc[0]["pnl_pct_max_loss_net"])
