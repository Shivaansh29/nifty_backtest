"""Tests on the real NSE cache in data/. They run locally and skip when the cache is absent.

Expected values were read by hand from the raw CSV inside each zip, independently of the
normaliser, so these tests check the normaliser against NSE's own files.
"""

from datetime import date

import pytest

from nifty_backtest.marketdata.bhavcopy import parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import read_log
from nifty_backtest.marketdata.quality import compare_formats
from nifty_backtest.marketdata.sources import Format, raw_path

pytestmark = pytest.mark.realdata


def cached(cfg: DataConfig, fmt: Format, day: date) -> bool:
    return raw_path(cfg, fmt, day).exists()


def test_hand_traced_row_3_jun_2024(real_cfg: DataConfig) -> None:
    # Raw UDiFF line, 3 Jun 2024, NIFTY 6 Jun 2024 21950 PE:
    # OpnPric 50.05, HghPric 54.50, LwPric 31.45, ClsPric 39.90, LastPric 39.15,
    # OpnIntrst 134350, ChngInOpnIntrst 7275, TtlTradgVol 64184, NewBrdLotQty 25,
    # UndrlygPric 23263.90
    day = date(2024, 6, 3)
    for fmt in Format:
        if not cached(real_cfg, fmt, day):
            pytest.skip(f"{fmt.value} file for {day} not cached")
        frame = parse(raw_path(real_cfg, fmt, day), fmt, day, ("NIFTY",))
        row = frame[
            (frame["expiry"] == date(2024, 6, 6))
            & (frame["strike"] == 21950)
            & (frame["option_type"] == "PE")
        ].iloc[0]
        assert (row["open"], row["high"], row["low"], row["close"]) == (50.05, 54.5, 31.45, 39.9)
        assert (row["contracts"], row["open_interest"], row["change_in_oi"]) == (
            64184,
            134350,
            7275,
        )
        if fmt is Format.UDIFF:
            assert (row["lot_size"], row["underlying_price"]) == (25, 23263.9)


def test_udiff_lot_size_before_and_after_the_2024_change(real_cfg: DataConfig) -> None:
    # Both values read from NewBrdLotQty in the raw files: every NIFTY option row agrees.
    for day, lot in [(date(2024, 1, 2), 50), (date(2024, 6, 3), 25)]:
        if not cached(real_cfg, Format.UDIFF, day):
            pytest.skip(f"UDiFF file for {day} not cached")
        frame = parse(raw_path(real_cfg, Format.UDIFF, day), Format.UDIFF, day, ("NIFTY",))
        assert set(frame["lot_size"]) == {lot}


def test_every_overlap_day_agrees_between_formats(real_cfg: DataConfig) -> None:
    days = sorted(
        d
        for (d, fmt), row in read_log(real_cfg).items()
        if fmt is Format.UDIFF
        and row["status"] == "ok"
        and cached(real_cfg, Format.LEGACY, d)
        and cached(real_cfg, Format.UDIFF, d)
    )
    if not days:
        pytest.skip("no day with both formats cached")
    for day in days:
        result = compare_formats(real_cfg, day)
        assert result.matched == result.legacy_rows == result.udiff_rows, day
        assert result.mismatched_columns == (), day
