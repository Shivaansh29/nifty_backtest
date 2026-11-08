"""M9 cost additions (plan §6): exercise of a BOUGHT leg, and the `gst_on_ipft` setting.

Hand calculations use the committed rate table (reference/cost_rates.csv).
"""

import csv
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.costs.model import (
    CostConfig,
    RateTable,
    long_expiry_charges,
    option_purchase_charges,
    option_sale_charges,
)

RATES = Path(__file__).resolve().parents[1] / "reference" / "cost_rates.csv"
TABLE = RateTable(RATES)


def test_exercise_stt_basis_is_intrinsic_value_in_the_rate_table() -> None:
    # NSE/FATAX/41919 and the Finance (No. 2) Act 2019: since 1 Sep 2019 STT on exercise is on
    # the intrinsic value, not the settlement value (plan §6.3).
    with RATES.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["applies_to"] == "option_exercise"]
    assert len(rows) == 2
    assert {r["basis"] for r in rows} == {"intrinsic_value"}
    assert all("NSE/FATAX/41919" in r["source"] for r in rows)


def test_exercised_bought_leg_pays_stt_on_intrinsic_value_and_sebi_on_notional() -> None:
    # Plan §6.4: expiry 5 Jun 2025, long 25000 CE, settlement 25,100, lot 75.
    # STT 0.125% x (100 x 75) = 9.375; SEBI 0.0001% x 25,100 x 75 = 1.8825; GST 18% of SEBI.
    c = long_expiry_charges(TABLE, date(2025, 6, 5), intrinsic_rs=100 * 75, notional_rs=25100 * 75)
    assert c.stt == pytest.approx(9.375)
    assert c.sebi == pytest.approx(1.8825)
    assert c.gst == pytest.approx(0.18 * 1.8825)
    assert c.brokerage == c.stamp == c.exchange == c.ipft == 0.0
    assert c.total == pytest.approx(9.375 + 1.8825 * 1.18)


def test_exercise_stt_rate_changes_on_1_april_2026() -> None:
    before = long_expiry_charges(TABLE, date(2026, 3, 31), intrinsic_rs=10_000, notional_rs=0)
    after = long_expiry_charges(TABLE, date(2026, 4, 1), intrinsic_rs=10_000, notional_rs=0)
    assert before.stt == pytest.approx(12.5)  # 0.125%
    assert after.stt == pytest.approx(15.0)  # 0.15%, NSE/FATAX/73524


def test_bought_leg_expiring_worthless_pays_nothing() -> None:
    assert long_expiry_charges(TABLE, date(2025, 6, 5), 0.0, 0.0).total == 0.0


def test_gst_on_ipft_is_off_by_default_so_history_is_unchanged() -> None:
    assert CostConfig().gst_on_ipft is False
    c = option_sale_charges(TABLE, CostConfig(), date(2025, 6, 2), 10_000.0)
    assert c.ipft > 0
    assert c.gst == pytest.approx(0.18 * (c.brokerage + c.exchange + c.sebi))


@pytest.mark.parametrize("charges", [option_sale_charges, option_purchase_charges])
def test_gst_on_ipft_adds_exactly_18_percent_of_ipft(charges: object) -> None:
    on, premium = date(2025, 6, 2), 10_000.0
    off = charges(TABLE, CostConfig(), on, premium)  # type: ignore[operator]
    on_ = charges(TABLE, CostConfig(gst_on_ipft=True), on, premium)  # type: ignore[operator]
    assert on_.gst == pytest.approx(0.18 * (on_.brokerage + on_.exchange + on_.ipft + on_.sebi))
    assert on_.gst - off.gst == pytest.approx(0.18 * off.ipft)
    for line in ("brokerage", "stt", "exchange", "ipft", "sebi", "stamp"):
        assert getattr(on_, line) == getattr(off, line)
