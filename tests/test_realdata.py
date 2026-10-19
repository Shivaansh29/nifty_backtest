"""Tests on the real NSE cache in data/. They run locally and skip when the cache is absent.

Expected values were read by hand from the raw CSV inside each zip, independently of the
normaliser, so these tests check the normaliser against NSE's own files.
"""

from datetime import date

import pandas as pd
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


def _stored(real_cfg: DataConfig) -> None:
    if not any(real_cfg.processed_dir.glob("*/*.parquet")):
        pytest.skip("no stored Parquet data; run `nifty-backtest build`")


def test_settle_column_trap_on_6_jun_2024(real_cfg: DataConfig) -> None:
    # Raw UDiFF/legacy rows for 6 Jun 2024 (an expiry day): every expiring NIFTY option shows
    # 22821.40 in the settle column, e.g. the 22000 CE (close 807.80) and 22000 PE (close 0.10).
    # 22821.40 is NIFTY's official close that day (NSE index API and ind_close_all agree).
    from nifty_backtest.marketdata.settlement import intrinsic_value, settlement_level
    from nifty_backtest.marketdata.store import connect

    _stored(real_cfg)
    with connect(real_cfg) as con:
        level = settlement_level(con, date(2024, 6, 6))
    assert level == 22821.40
    assert intrinsic_value("CE", 22000, level) == pytest.approx(821.40)


def test_expiry_calendar_edge_cases(real_cfg: DataConfig) -> None:
    from nifty_backtest.marketdata.store import connect
    from nifty_backtest.marketdata.trading_calendar import expiry_calendar, special_sessions

    _stored(real_cfg)
    with connect(real_cfg) as con:
        calendar = expiry_calendar(con, real_cfg, entry_days_before=3).set_index("expiry")
    assert (calendar["status"] == "ok").all()
    # 29 Jun 2023 became a holiday: the contract still said 29 Jun on entry (Fri 23 Jun)
    # but expired Wed 28 Jun.
    jun = calendar.loc[date(2023, 6, 28)]
    assert (jun["entry_date"], jun["stated_expiry_on_entry"]) == (
        date(2023, 6, 23),
        date(2023, 6, 29),
    )
    # 30 Jan 2025 expiry kept lot 25 while the weeks around it had 75.
    assert calendar.loc[date(2025, 1, 30)]["lot_size_at_entry"] == 25
    assert calendar.loc[date(2025, 1, 23)]["lot_size_at_entry"] == 75
    # Thursday -> Tuesday switch: the 2 Sep 2025 trade enters on the previous expiry day.
    assert calendar.loc[date(2025, 9, 2)]["entry_date"] == date(2025, 8, 28)
    # No entry ever falls on a short special session.
    short = {d for d, s in special_sessions(real_cfg).items() if s.short_session}
    assert not set(calendar["entry_date"]) & short


def test_lot_size_sources_across_the_window(real_cfg: DataConfig) -> None:
    from nifty_backtest.marketdata.store import query

    _stored(real_cfg)
    rows = query(
        real_cfg,
        """
        SELECT trade_date, any_value(lot_size) AS lot, any_value(lot_size_source) AS src
        FROM options WHERE trade_date IN ('2022-06-15', '2024-02-01', '2024-04-26')
        GROUP BY trade_date ORDER BY trade_date
        """,
    )
    assert rows["lot"].tolist() == [50, 50, 25]
    assert rows["src"].tolist() == ["reference_table", "udiff_same_day", "udiff_same_day"]


def test_index_values_against_nse_archive_files(real_cfg: DataConfig) -> None:
    # Values read by hand from NSE's ind_close_all_01102021.csv / _02032024.csv and the
    # niftyindices TRI answer for 1 Oct 2021.
    from nifty_backtest.marketdata.indices import index_path

    path = index_path(real_cfg)
    if not path.exists():
        pytest.skip("no index data stored")
    index = pd.read_parquet(path).set_index("date")
    oct1 = index.loc[date(2021, 10, 1)]
    assert (oct1["nifty_close"], oct1["vix_close"], oct1["nifty_tri"]) == (
        17532.05,
        17.21,
        25111.25,
    )
    mar2 = index.loc[date(2024, 3, 2)]  # missing from NSE's API; filled from the archive
    assert (mar2["nifty_close"], mar2["vix_close"], mar2["nifty_vix_source"]) == (
        22378.4, 14.99, "nse_archive",
    )  # fmt: skip


def test_every_weekday_without_a_session_is_an_official_holiday(real_cfg: DataConfig) -> None:
    from nifty_backtest.marketdata.holidays import fo_holidays

    holidays = fo_holidays(real_cfg, today=date.today())
    if not holidays:
        pytest.skip("no cached holiday lists")
    stored = sorted(real_cfg.processed_dir.glob("*/*.parquet"))
    last = date.fromisoformat(stored[-1].stem)
    gaps = [
        d
        for (d, fmt), row in read_log(real_cfg).items()
        if row["status"] == "not_found" and d.weekday() < 5 and d <= last
        and fmt.value == ("legacy" if d <= real_cfg.legacy_last_date else "udiff")
        and d not in holidays
    ]  # fmt: skip
    assert gaps == []
