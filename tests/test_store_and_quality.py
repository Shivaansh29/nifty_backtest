"""Parquet storage, DuckDB queries and the data-quality report, on synthetic data."""

import csv
from dataclasses import replace
from datetime import date

import pandas as pd

from nifty_backtest.marketdata.bhavcopy import COLUMNS
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import log_path
from nifty_backtest.marketdata.quality import build_report, compare_formats
from nifty_backtest.marketdata.sources import Format
from nifty_backtest.marketdata.store import build, processed_path, query
from tests.helpers import FIXTURE_DAY, install_fixture


def write_log(cfg: DataConfig, rows: list[tuple[date, Format, str]]) -> None:
    path = log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "format", "status", "http_status", "bytes", "checked_at"])
        for day, fmt, status in rows:
            writer.writerow([day.isoformat(), fmt.value, status, "", 0, "2026-01-01T00:00:00"])


def test_build_stores_one_parquet_per_day_and_is_incremental(cfg: DataConfig) -> None:
    install_fixture(cfg, Format.LEGACY)  # 2024-02-01 is in the legacy (primary) period
    assert build(cfg, today=date(2026, 1, 1)) == (1, 0)
    assert processed_path(cfg, FIXTURE_DAY).exists()
    assert build(cfg, today=date(2026, 1, 1)) == (0, 1)  # nothing new to do


def test_duckdb_reads_the_stored_rows(cfg: DataConfig) -> None:
    install_fixture(cfg, Format.LEGACY)
    build(cfg, today=date(2026, 1, 1))
    result = query(cfg, "SELECT count(*) AS n, sum(contracts) AS c FROM options")
    assert result.iloc[0].tolist() == [3, 1010]


def test_overlap_comparison_finds_no_mismatch(cfg: DataConfig) -> None:
    install_fixture(cfg, Format.LEGACY)
    install_fixture(cfg, Format.UDIFF)
    result = compare_formats(cfg, FIXTURE_DAY)
    assert (result.legacy_rows, result.udiff_rows, result.matched) == (3, 3, 3)
    assert result.mismatched_columns == ()
    assert result.max_turnover_diff_rs == 500.0  # 110.02 lakh vs Rs 11,002,500


def test_report_sections(cfg: DataConfig) -> None:
    install_fixture(cfg, Format.LEGACY)
    install_fixture(cfg, Format.UDIFF)
    build(cfg, today=date(2026, 1, 1))
    write_log(
        cfg,
        [
            (date(2024, 2, 1), Format.LEGACY, "ok"),
            (date(2024, 2, 1), Format.UDIFF, "ok"),
            (date(2024, 2, 2), Format.LEGACY, "error"),  # a Friday that failed to download
            (date(2024, 2, 3), Format.LEGACY, "not_found"),  # Saturday, no session
        ],
    )
    report = build_report(cfg, today=date(2026, 1, 1))

    assert "Trading days stored: **1**" in report
    assert "Download errors still unresolved: 1: 2024-02-02" in report
    assert "Dates with no session (NSE returned 404): 1, of which 0 are weekdays" in report
    assert "Days where every contract matched and every shared column agreed: **1**" in report
    # Zero-volume table: 3 rows that day, 1 of them with no trades.
    assert "| 2024 | 3 | 1 | 33.3 |" in report


def _row(trade_day: date, expiry: date, lot: int) -> dict[str, object]:
    return {
        "trade_date": trade_day, "underlying": "NIFTY", "expiry": expiry, "strike": 22000.0,
        "option_type": "CE", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
        "settle_price": 1.0, "contracts": 1, "turnover_rs": 1.0, "open_interest": 1,
        "change_in_oi": 0, "lot_size": lot, "underlying_price": 22000.0,
        "zero_volume": False, "source_format": "udiff",
    }  # fmt: skip


def test_report_counts_only_expiries_that_happened_and_mid_life_lot_changes(
    cfg: DataConfig,
) -> None:
    # Two trading days. Contract A (expiry Thu 2025-08-07) trades on both days, including its
    # expiry day, and its lot changes 75 -> 65 mid-life. Contract B states an expiry of
    # Tue 2025-08-05 but is last seen on day 1: it never reached that date.
    day1, day2 = date(2025, 8, 4), date(2025, 8, 7)
    a, b = date(2025, 8, 7), date(2025, 8, 5)
    frames = {day1: [_row(day1, a, 75), _row(day1, b, 75)], day2: [_row(day2, a, 65)]}
    for day, rows in frames.items():
        path = processed_path(cfg, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame(rows, columns=COLUMNS).astype({"lot_size": "Int64"})
        frame.to_parquet(path, index=False)
    cfg = replace(cfg, start=day1, end=day2)
    write_log(cfg, [(day1, Format.UDIFF, "ok"), (day2, Format.UDIFF, "ok")])

    report = build_report(cfg, today=date(2026, 1, 1))

    assert "| 2025 | 0 | 0 | 0 | 1 | 0 | 1 |" in report  # only Thu 7 Aug happened
    assert "| 2025-08-05 | Tuesday | 2025-08-04 |" in report  # B never arrived
    assert "| 2025-08-07 | 75 | 65 | 1 |" in report  # A changed lot while trading
    assert "same day (should be 0): **0**" in report
