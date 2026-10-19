"""File names, URLs and format selection, checked against real NSE file names."""

from datetime import date

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.sources import (
    Format,
    file_name,
    formats_to_download,
    primary_format,
    url,
)


def test_legacy_name_and_url_match_nse() -> None:
    # Real file downloaded on 2026-10-09: .../DERIVATIVES/2021/OCT/fo01OCT2021bhav.csv.zip
    day = date(2021, 10, 1)
    assert file_name(Format.LEGACY, day) == "fo01OCT2021bhav.csv.zip"
    assert url(Format.LEGACY, day) == (
        "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/2021/OCT/"
        "fo01OCT2021bhav.csv.zip"
    )


def test_udiff_name_and_url_match_nse() -> None:
    day = date(2024, 7, 8)
    assert file_name(Format.UDIFF, day) == "BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip"
    assert url(Format.UDIFF, day) == (
        "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip"
    )


def test_formats_by_period() -> None:
    cfg = DataConfig()
    # Before the overlap: legacy only. Inside it: both. After the last legacy file: UDiFF.
    assert formats_to_download(cfg, date(2023, 12, 29)) == [Format.LEGACY]
    assert formats_to_download(cfg, date(2024, 1, 1)) == [Format.LEGACY, Format.UDIFF]
    assert formats_to_download(cfg, date(2024, 7, 5)) == [Format.LEGACY, Format.UDIFF]
    assert formats_to_download(cfg, date(2024, 7, 8)) == [Format.UDIFF]
    # Legacy stays the stored source for the whole overlap, as in the spec.
    assert primary_format(cfg, date(2024, 7, 5)) is Format.LEGACY
    assert primary_format(cfg, date(2024, 7, 6)) is Format.UDIFF
