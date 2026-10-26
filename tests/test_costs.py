"""Cost model: dated rate lookup and hand-computed charges (using the committed rate table)."""

from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.costs.model import (
    CostConfig,
    RateTable,
    option_purchase_charges,
    option_sale_charges,
    short_expiry_charges,
)

TABLE = RateTable(Path(__file__).resolve().parents[1] / "reference" / "cost_rates.csv")
CFG = CostConfig(brokerage_per_order_rs=20.0)


@pytest.mark.parametrize(
    ("day", "stt", "exchange"),
    [
        # Each STT / NSE transaction-charge change, checked on its last old and first new day.
        (date(2023, 3, 31), 0.0005, 0.00053),  # STT 0.05%, NSE Rs 53/lakh
        (date(2023, 4, 1), 0.000625, 0.0005),  # Finance Act 2023; NSE/FA/56129
        (date(2024, 3, 31), 0.000625, 0.0005),
        (date(2024, 4, 1), 0.000625, 0.000495),  # NSE/FA/61137
        (date(2024, 9, 30), 0.000625, 0.000495),
        (date(2024, 10, 1), 0.001, 0.0003503),  # Finance Act 2024; NSE/FA/64232
        (date(2026, 2, 28), 0.001, 0.0003503),
        (date(2026, 3, 1), 0.001, 0.000355299),  # NSE/FA/73061
        (date(2026, 3, 31), 0.001, 0.000355299),
        (date(2026, 4, 1), 0.0015, 0.000355299),  # Finance Act 2026
    ],
)
def test_rates_switch_on_their_effective_dates(day: date, stt: float, exchange: float) -> None:
    assert TABLE.rate("stt", "option_sale", day) == stt
    assert TABLE.rate("exchange_txn", "option_trade", day) == exchange


def test_ipft_rose_in_april_2023_and_fell_back_in_march_2026() -> None:
    assert TABLE.rate("ipft", "option_trade", date(2023, 3, 31)) == 0.000000001  # Rs 0.01/cr
    assert TABLE.rate("ipft", "option_trade", date(2023, 4, 1)) == 0.000005  # Rs 50/cr
    assert TABLE.rate("ipft", "option_trade", date(2026, 3, 1)) == 0.000000001


def test_sale_charges_hand_computed_3_jun_2024() -> None:
    # The real 3 Jun 2024 entry: CE filled at 348.80 x 25 units = Rs 8,720.00 of premium.
    # Rates in force: STT 0.0625%, NSE 0.0495%, IPFT 0.0005%, SEBI 0.0001%, GST 18%.
    c = option_sale_charges(TABLE, CFG, date(2024, 6, 3), 8720.00)
    assert c.brokerage == 20.0
    assert c.stt == pytest.approx(5.45)  # 8720.00 x 0.000625
    assert c.exchange == pytest.approx(4.3164)  # 8720.00 x 0.000495
    assert c.ipft == pytest.approx(0.0436)  # 8720.00 x 0.000005
    assert c.sebi == pytest.approx(0.00872)  # 8720.00 x 0.000001
    assert c.gst == pytest.approx(4.3785216)  # 0.18 x (20 + 4.3164 + 0.00872) = 0.18 x 24.32512
    assert c.stamp == 0.0  # a sale pays no stamp duty
    assert c.total == pytest.approx(34.1972416)
    # With the PE leg (Rs 33.3009726) this gives Rs 67.4982142, the entry charges of the
    # real trade traced by hand in test_realdata.py.


def test_assigned_short_leg_pays_sebi_fee_on_notional_and_gst() -> None:
    # PE assigned on 6 Jun 2024: notional = 22821.40 x 25 = Rs 5,70,535.
    c = short_expiry_charges(TABLE, date(2024, 6, 6), 570_535.0)
    assert (c.brokerage, c.stt, c.exchange) == (0.0, 0.0, 0.0)  # no order, purchaser pays STT
    assert c.sebi == pytest.approx(0.570535)
    assert c.gst == pytest.approx(0.1026963)


def test_out_of_the_money_short_leg_expires_free() -> None:
    assert short_expiry_charges(TABLE, date(2024, 6, 6), 0.0).total == 0.0


def write_table(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "rates.csv"
    header = "charge,applies_to,basis,rate,effective_from,payer,source,source_url,note"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_every_rate_needs_a_source(tmp_path: Path) -> None:
    path = write_table(tmp_path, ["stt,option_sale,premium,0.001,2024-10-01,seller,,u,"])
    with pytest.raises(ValueError, match="no source"):
        RateTable(path)


def test_duplicate_start_dates_are_rejected(tmp_path: Path) -> None:
    rows = ["stt,option_sale,premium,0.001,2024-10-01,seller,s,u,"] * 2
    with pytest.raises(ValueError, match="share"):
        RateTable(write_table(tmp_path, rows))


def test_no_rate_before_the_first_row_is_an_error() -> None:
    with pytest.raises(LookupError):
        TABLE.rate("stt", "option_sale", date(2020, 1, 1))


def test_buy_back_charges_hand_computed_5_aug_2025() -> None:
    # M7: buying back a short leg at 239.00 x 75 = Rs 17,925 on 5 Aug 2025.
    # Rates in force: NSE 0.03503%, IPFT Rs 50/crore (0.0005%), SEBI Rs 10/crore (0.0001%),
    # stamp duty 0.003% (buyer), GST 18%; brokerage Rs 20. No STT on a purchase.
    #   exchange 17,925 x 0.0003503     = 6.2791275
    #   ipft     17,925 x 0.000005      = 0.089625
    #   sebi     17,925 x 0.000001      = 0.017925
    #   stamp    17,925 x 0.00003       = 0.53775
    #   gst      0.18 x (20 + 6.2791275 + 0.017925) = 4.73346945
    #   total    = 31.65789695
    c = option_purchase_charges(TABLE, CFG, date(2025, 8, 5), 17_925.0)
    assert (c.brokerage, c.stt) == (20.0, 0.0)
    assert c.exchange == pytest.approx(6.2791275)
    assert c.ipft == pytest.approx(0.089625)
    assert c.sebi == pytest.approx(0.017925)
    assert c.stamp == pytest.approx(0.53775)
    assert c.gst == pytest.approx(4.73346945)
    assert c.total == pytest.approx(31.65789695)
