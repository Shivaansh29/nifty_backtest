"""Expiry settlement (trap 3): intrinsic value and the settle-column rule."""

from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.settlement import SettlementError, intrinsic_value, settlement_level
from nifty_backtest.marketdata.store import connect
from tests.helpers import option_row, write_processed

EXPIRY = date(2024, 6, 6)


@pytest.mark.parametrize(
    ("option_type", "strike", "expected"),
    [
        # Worked by hand with a settlement level of 22821.40 (the real 6 Jun 2024 level):
        ("CE", 22000.0, 821.40),  # 22821.40 - 22000
        ("PE", 22000.0, 0.0),  # out of the money
        ("PE", 23000.0, 178.60),  # 23000 - 22821.40
        ("CE", 23000.0, 0.0),
        ("CE", 22821.40, 0.0),  # exactly at the money
    ],
)
def test_intrinsic_value(option_type: str, strike: float, expected: float) -> None:
    assert intrinsic_value(option_type, strike, 22821.40) == pytest.approx(expected)


def test_unknown_option_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="option type"):
        intrinsic_value("XX", 22000.0, 22000.0)


def test_settle_column_on_expiry_day_is_the_index_level(cfg: DataConfig) -> None:
    # On expiry day the expiring contracts all carry the index settlement level in their
    # settle column; a contract expiring later carries its own price (ignored).
    rows = [
        option_row(EXPIRY, EXPIRY, strike=k, option_type=t, settle=22821.40)
        for k in (22000.0, 23000.0)
        for t in ("CE", "PE")
    ]
    rows.append(option_row(EXPIRY, date(2024, 6, 13), settle=150.25))
    write_processed(cfg, rows)
    with connect(cfg) as con:
        assert settlement_level(con, EXPIRY) == 22821.40


def test_disagreeing_settle_values_stop_instead_of_picking_one(cfg: DataConfig) -> None:
    write_processed(
        cfg,
        [
            option_row(EXPIRY, EXPIRY, option_type="CE", settle=22821.40),
            option_row(EXPIRY, EXPIRY, option_type="PE", settle=22800.00),
        ],
    )
    with connect(cfg) as con, pytest.raises(SettlementError, match="disagree"):
        settlement_level(con, EXPIRY)


def test_no_expiring_contracts_is_an_error(cfg: DataConfig, tmp_path: Path) -> None:
    write_processed(cfg, [option_row(EXPIRY, date(2024, 6, 13))])
    with connect(cfg) as con, pytest.raises(SettlementError, match="no expiring"):
        settlement_level(con, EXPIRY)
