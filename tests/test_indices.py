"""Index, VIX, TRI and holiday parsing, with responses shaped like NSE's real ones."""

import json
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.holidays import fo_holidays, holiday_path
from nifty_backtest.marketdata.indices import IndexDataError, _archive_row, _rows, months

OCT_1, OCT_31 = date(2021, 10, 1), date(2021, 10, 31)


def nse(name: str, day: str, close: float) -> bytes:
    """An NSE indicesHistory / vixhistory answer with one row (field names as NSE sends)."""
    row = {
        "EOD_INDEX_NAME": name, "EOD_TIMESTAMP": day, "EOD_OPEN_INDEX_VAL": close - 1,
        "EOD_HIGH_INDEX_VAL": close + 5, "EOD_LOW_INDEX_VAL": close - 5,
        "EOD_CLOSE_INDEX_VAL": close,
    }  # fmt: skip
    return json.dumps({"data": [row]}).encode()


def test_months_are_clipped_to_the_window() -> None:
    assert list(months(date(2021, 10, 15), date(2022, 1, 10))) == [
        (date(2021, 10, 15), date(2021, 10, 31)),
        (date(2021, 11, 1), date(2021, 11, 30)),
        (date(2021, 12, 1), date(2021, 12, 31)),
        (date(2022, 1, 1), date(2022, 1, 10)),
    ]


def test_nifty_and_vix_rows() -> None:
    nifty = _rows("nifty", nse("NIFTY 50", "01-OCT-2021", 17532.05), OCT_1, OCT_31)
    assert nifty.iloc[0].to_dict() == {
        "date": OCT_1, "nifty_open": 17531.05, "nifty_high": 17537.05,
        "nifty_low": 17527.05, "nifty_close": 17532.05,
    }  # fmt: skip
    vix = _rows("vix", nse("INDIA VIX", "01-OCT-2021", 17.21), OCT_1, OCT_31)
    assert vix.iloc[0]["vix_close"] == 17.21


def test_tri_rows_and_name_case() -> None:
    answer = [
        {"Index Name": "Nifty 50", "Date": "01 Oct 2021", "TotalReturnsIndex": "25111.25"},
        {"Index Name": "NIFTY 50", "Date": "04 Oct 2021", "TotalReturnsIndex": "25339.32"},
    ]
    tri = _rows("tri", json.dumps(answer).encode(), OCT_1, OCT_31)
    assert tri["nifty_tri"].tolist() == [25111.25, 25339.32]  # case varies, both accepted


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (nse("NIFTY BANK", "01-OCT-2021", 1.0), "index names"),  # wrong index
        (nse("NIFTY 50", "01-NOV-2021", 1.0), "outside the requested month"),
        (b"<html>maintenance</html>", "not JSON"),
    ],
)
def test_unexpected_answers_stop_the_download(content: bytes, message: str) -> None:
    with pytest.raises(IndexDataError, match=message):
        _rows("nifty", content, OCT_1, OCT_31)


ARCHIVE_HEADER = (
    "Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,"
    "Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.),P/E,P/B,Div Yield"
)


def test_archive_file_row() -> None:
    # Header and line layout copied from NSE's ind_close_all file; values made up.
    content = "\n".join(
        [
            ARCHIVE_HEADER,
            "Nifty 50,02-03-2024,100.5,101,99,100.25,1,1,1,1,1,1,1",
            "Nifty Bank,02-03-2024,1,1,1,1,1,1,1,1,1,1,1",
            "India VIX,02-03-2024,15,16,14,15.5,0,0,-,-,-,-,-",
        ]
    ).encode()
    row = _archive_row(content, date(2024, 3, 2)).iloc[0]
    assert (row["nifty_close"], row["vix_close"], row["vix_high"]) == (100.25, 15.5, 16.0)
    with pytest.raises(IndexDataError, match="dated"):
        _archive_row(content, date(2024, 3, 4))


def test_fo_holidays_are_read_from_the_cached_lists(tmp_path: Path) -> None:
    cfg = DataConfig(data_dir=tmp_path, start=date(2024, 1, 1), end=date(2024, 12, 31))
    path = holiday_path(cfg, 2024)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "CM": [{"tradingDate": "01-Jan-2024", "description": "not F&O"}],
                "FO": [{"tradingDate": "22-Jan-2024", "description": "Special Holiday\r"}],
            }
        )
    )
    assert fo_holidays(cfg, today=date(2024, 12, 31)) == {date(2024, 1, 22): "Special Holiday"}
