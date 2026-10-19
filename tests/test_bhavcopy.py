"""Normaliser tests on the synthetic fixtures (real column layout, made-up values)."""

import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nifty_backtest.marketdata.bhavcopy import COLUMNS, BhavcopyError, legacy_date, parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.sources import Format
from tests.helpers import FIXTURE_DAY, install_fixture

NIFTY = ("NIFTY",)


def parsed(cfg: DataConfig, fmt: Format) -> pd.DataFrame:
    return parse(install_fixture(cfg, fmt), fmt, FIXTURE_DAY, NIFTY)


def test_legacy_dates_are_parsed_without_locale() -> None:
    assert legacy_date("27-Jun-2024") == date(2024, 6, 27)
    assert legacy_date("03-JUN-2024") == date(2024, 6, 3)


@pytest.mark.parametrize("fmt", list(Format))
def test_keeps_only_nifty_index_options(cfg: DataConfig, fmt: Format) -> None:
    frame = parsed(cfg, fmt)
    # 6 rows in the file; the future, the BANKNIFTY option and the stock option are dropped.
    assert list(frame.columns) == COLUMNS
    assert len(frame) == 3
    assert set(frame["underlying"]) == {"NIFTY"}
    assert set(frame["source_format"]) == {fmt.value}


@pytest.mark.parametrize("fmt", list(Format))
def test_hand_checked_row(cfg: DataConfig, fmt: Format) -> None:
    # Values copied by hand from the fixture line for the 8 Feb 2024 21700 CE.
    frame = parsed(cfg, fmt)
    row = frame[(frame["strike"] == 21700) & (frame["option_type"] == "CE")].iloc[0]
    assert row["trade_date"] == date(2024, 2, 1)
    assert row["expiry"] == date(2024, 2, 8)
    assert (row["open"], row["high"], row["low"], row["close"]) == (150.0, 180.0, 120.5, 160.25)
    assert row["contracts"] == 1000
    assert row["open_interest"] == 500000
    assert row["change_in_oi"] == 25000
    assert row["turnover_rs"] == 1_092_500_000.0  # legacy: 10925.00 lakh x 100,000
    assert not row["zero_volume"]


def test_zero_volume_row_is_flagged(cfg: DataConfig) -> None:
    frame = parsed(cfg, Format.UDIFF)
    stale = frame[frame["zero_volume"]]
    assert len(stale) == 1
    assert stale.iloc[0]["close"] == 95.5  # the carried-forward price is kept, but flagged


def test_lot_size_and_underlying_price_only_in_udiff(cfg: DataConfig) -> None:
    udiff, legacy = parsed(cfg, Format.UDIFF), parsed(cfg, Format.LEGACY)
    assert set(udiff["lot_size"]) == {50}
    assert legacy["lot_size"].isna().all()
    assert legacy["underlying_price"].isna().all()


def test_both_formats_normalise_to_the_same_rows(cfg: DataConfig) -> None:
    only_one_format = ("lot_size", "underlying_price", "source_format")
    exact = [c for c in COLUMNS if c not in (*only_one_format, "turnover_rs")]
    legacy, udiff = parsed(cfg, Format.LEGACY), parsed(cfg, Format.UDIFF)
    pd.testing.assert_frame_equal(legacy[exact], udiff[exact])
    # Legacy turnover is in lakhs to 2 decimals, so it is only precise to Rs 1,000.
    assert (legacy["turnover_rs"] - udiff["turnover_rs"]).abs().max() < 1_000


def _rewrite(path: Path, edit: str, replacement: str) -> None:
    with zipfile.ZipFile(path) as archive:
        name = archive.namelist()[0]
        text = archive.read(name).decode()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name, text.replace(edit, replacement))


def test_wrong_trade_date_is_rejected(cfg: DataConfig) -> None:
    path = install_fixture(cfg, Format.UDIFF)
    with pytest.raises(BhavcopyError, match="trade dates"):
        parse(path, Format.UDIFF, date(2024, 2, 2), NIFTY)


def test_differing_expiry_columns_stop_the_parser(cfg: DataConfig) -> None:
    # Trap 7: if NSE's two expiry columns ever disagree, don't guess which one is right.
    path = install_fixture(cfg, Format.UDIFF)
    _rewrite(path, "2024-02-08,2024-02-08,21700.00,CE", "2024-02-08,2024-02-07,21700.00,CE")
    with pytest.raises(BhavcopyError, match="XpryDt"):
        parse(path, Format.UDIFF, FIXTURE_DAY, NIFTY)


def test_missing_column_is_reported(cfg: DataConfig) -> None:
    path = install_fixture(cfg, Format.LEGACY)
    _rewrite(path, "SETTLE_PR", "SETTLE_PRICE")
    with pytest.raises(BhavcopyError, match="missing columns"):
        parse(path, Format.LEGACY, FIXTURE_DAY, NIFTY)
