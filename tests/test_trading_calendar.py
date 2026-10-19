"""Expiry calendar rules (traps 1 and 6) on small hand-built data sets.

Dates are a real week (4-8 Aug 2025) but every row is made up.
"""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.store import connect
from nifty_backtest.marketdata.trading_calendar import expiry_calendar, special_sessions
from tests.helpers import option_row, write_processed, write_special_sessions

MON, TUE, WED, THU = date(2025, 8, 4), date(2025, 8, 5), date(2025, 8, 6), date(2025, 8, 7)
FRI, NEXT_THU = date(2025, 8, 8), date(2025, 8, 14)


def setup(cfg: DataConfig, tmp_path: Path, short: list[date] | None = None) -> DataConfig:
    ref = tmp_path / "ref"
    write_special_sessions(ref, [(d.isoformat(), "muhurat", "true") for d in short or []])
    return replace(cfg, reference_dir=ref)


def test_entry_counts_back_full_sessions_and_skips_short_ones(
    cfg: DataConfig, tmp_path: Path
) -> None:
    # One contract expiring Thu, trading Mon-Thu. Tue is a short (Muhurat-style) session.
    cfg = setup(cfg, tmp_path, short=[TUE])
    write_processed(cfg, [option_row(d, THU, 75) for d in (MON, TUE, WED, THU)])
    with connect(cfg) as con:
        two_back = expiry_calendar(con, cfg, entry_days_before=2).iloc[0]
        three_back = expiry_calendar(con, cfg, entry_days_before=3).iloc[0]
    # Full sessions before Thu: Mon, Wed (Tue doesn't count). 2 back = Mon.
    assert two_back["entry_date"] == MON
    assert (two_back["status"], two_back["lot_size_at_entry"], two_back["relabelled"]) == (
        "ok",
        75,
        False,
    )
    assert three_back["status"] == "insufficient_history"


def test_redated_expiry_is_mapped_to_the_actual_one(cfg: DataConfig, tmp_path: Path) -> None:
    # Like 29 Jun 2023: the contract says Thu on Mon and Tue, then is re-dated and
    # actually expires on Wed. Thu passes (Thu and Fri trade other contracts) without it.
    cfg = setup(cfg, tmp_path)
    rows = [option_row(MON, THU), option_row(TUE, THU), option_row(WED, WED)]
    rows += [option_row(d, NEXT_THU) for d in (MON, TUE, WED, THU, FRI)]
    write_processed(cfg, rows)
    with connect(cfg) as con:
        calendar = expiry_calendar(con, cfg, entry_days_before=2)
    assert WED in set(calendar["expiry"])
    assert THU not in set(calendar["expiry"])  # stated, never real
    row = calendar.set_index("expiry").loc[WED]
    assert (row["entry_date"], row["stated_expiry_on_entry"]) == (MON, THU)
    assert (row["relabelled"], row["status"]) == (True, "ok")


def test_expiry_that_would_not_be_the_nearest_is_flagged(cfg: DataConfig, tmp_path: Path) -> None:
    # Two real expiries only two days apart: Tue and Thu.
    cfg = setup(cfg, tmp_path)
    rows = [option_row(d, TUE) for d in (MON, TUE)] + [
        option_row(d, THU) for d in (MON, TUE, WED, THU)
    ]
    write_processed(cfg, rows)
    with connect(cfg) as con:
        calendar = expiry_calendar(con, cfg, entry_days_before=3).set_index("expiry")
    # 3 sessions before Thu is Mon, but on Mon the nearest expiry is Tue, not Thu.
    assert calendar.loc[THU]["status"] == "not_nearest"


def test_special_sessions_need_a_source(tmp_path: Path) -> None:
    ref = tmp_path / "ref"
    ref.mkdir()
    (ref / "special_sessions.csv").write_text(
        "date,kind,short_session,fo_hours,source,source_url\n2024-03-02,dr_drill,true,x,,u\n"
    )
    with pytest.raises(ValueError, match="source"):
        special_sessions(DataConfig(reference_dir=ref))


def test_committed_special_sessions_file_is_valid() -> None:
    sessions = special_sessions(DataConfig())  # reads reference/special_sessions.csv
    assert sessions[date(2024, 1, 20)].short_session is False  # full day per NSE/MSD/60340
    assert sessions[date(2024, 3, 2)].short_session is True  # DR drill per NSE/MSD/60677
    assert all(s.source for s in sessions.values())
