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
from tests.helpers import REPO_DATA

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


def _one_trade(real_cfg: DataConfig, entry: date, expiry: date) -> dict[str, object]:
    from dataclasses import replace

    from nifty_backtest.engine.backtest import RunConfig, run_backtest
    from nifty_backtest.strategies.short_straddle import ShortStraddle

    _stored(real_cfg)
    run = RunConfig(data=replace(real_cfg, start=entry, end=expiry))
    result = run_backtest(run, ShortStraddle())
    assert result.skipped.empty
    trades = result.trades[result.trades["expiry"] == expiry]
    assert len(trades) == 1
    return dict(trades.iloc[0])


# The three trades below were traced by hand from NSE's raw files, with a script that uses
# none of the project's code (raw zip -> csv module). Inputs quoted in each comment.


def test_hand_traced_trade_event_week_4_jun_2024(real_cfg: DataConfig) -> None:
    # Entry Mon 3 Jun 2024 (3 sessions before Thu 6 Jun). NIFTY close 23,263.90
    # (ind_close_all_03062024.csv; = UDiFF UndrlygPric) -> ATM 23,250 (13.90 vs 36.10 away).
    # fo03JUN2024bhav: 23250 CE close 349.30 (908,306 contracts), PE close 319.80 (432,363).
    # Lot 25 (same-day UDiFF NewBrdLotQty). fo06JUN2024bhav: settle 22821.40 on both legs.
    # Premium 669.10; fills 668.10; PE worth 23,250 - 22,821.40 = 428.60; CE worth 0.
    # Gross 240.50 pts. Charges: entry 67.4982142 (see test_costs) + PE assignment 0.6732313.
    # Net = 239.50 x 25 - 68.1714455 = Rs 5,919.3285545. Election result (4 Jun) inside window.
    t = _one_trade(real_cfg, date(2024, 6, 3), date(2024, 6, 6))
    assert (t["entry_date"], t["strike"], t["quantity"]) == (date(2024, 6, 3), 23250.0, 25)
    assert (t["ce_entry_close"], t["pe_entry_close"]) == (349.30, 319.80)
    assert t["settlement_level"] == 22821.40
    assert t["value_at_expiry_points"] == pytest.approx(428.60)
    assert t["pnl_points_gross"] == pytest.approx(240.50)
    assert t["charges_rs"] == pytest.approx(68.1714455)
    assert t["pnl_rs_net"] == pytest.approx(5919.3285545)
    assert t["events"] == "general_election_result@2024-06-04"
    assert t["nifty_move_pct"] == pytest.approx((22821.40 / 23263.90 - 1) * 100)


def test_hand_traced_trade_lot_25_week_30_jan_2025(real_cfg: DataConfig) -> None:
    # Entry Mon 27 Jan 2025. UDiFF 20250127: UndrlygPric 22,829.15 -> ATM 22,850.
    # 22850 CE 152.80, PE 154.95, NewBrdLotQty 25 (the 30 Jan contract kept lot 25).
    # UDiFF 20250130: settle 23,249.50 -> CE worth 399.50, PE 0.
    # Gross 307.75 - 399.50 = -91.75 pts. Entry charges on Rs 7,668.75 at STT 0.1%,
    # NSE 0.03503%: 58.0860514; CE assignment 0.6858603. Net = -92.75 x 25 - 58.7719116.
    t = _one_trade(real_cfg, date(2025, 1, 27), date(2025, 1, 30))
    assert (t["strike"], t["lot_size"], t["lot_size_source"]) == (22850.0, 25, "udiff")
    assert t["pnl_points_gross"] == pytest.approx(-91.75)
    assert t["charges_rs"] == pytest.approx(58.7719116)
    assert t["pnl_rs_net"] == pytest.approx(-2377.5219116)


def test_hand_traced_first_trade_7_oct_2021(real_cfg: DataConfig) -> None:
    # Entry Mon 4 Oct 2021. ind_close_all_04102021: NIFTY 17,691.25 -> ATM 17,700.
    # fo04OCT2021bhav: 17700 CE 100.30, PE 92.95; lot 50 from reference/lot_sizes_legacy.csv.
    # fo07OCT2021bhav: settle 17,790.35 -> CE worth 90.35. Gross 193.25 - 90.35 = 102.90 pts.
    # Charges at STT 0.05%, NSE 0.053%: entry 58.0292597, CE assignment 1.0496307.
    # Net = 101.90 x 50 - 59.0788903 = Rs 5,035.9211097.
    t = _one_trade(real_cfg, date(2021, 10, 4), date(2021, 10, 7))
    assert (t["strike"], t["lot_size"], t["lot_size_source"]) == (17700.0, 50, "reference_table")
    assert t["pnl_points_gross"] == pytest.approx(102.90)
    assert t["charges_rs"] == pytest.approx(59.0788903)
    assert t["pnl_rs_net"] == pytest.approx(5035.9211097)


REPO_RUNS = REPO_DATA.parent / "runs"


def test_metrics_on_the_latest_saved_run_reconcile_with_m3() -> None:
    """Validation against the saved M3 run: every reconciliation holds, and for a default-cost
    run over the M3 data window the totals are exactly M3's."""
    import json

    from nifty_backtest.metrics.series import load_run
    from nifty_backtest.metrics.summary import compute_metrics

    folders = sorted(p for p in REPO_RUNS.glob("*-short_straddle") if (p / "trades.csv").exists())
    if not folders:
        pytest.skip("no saved runs; run `nifty-backtest backtest`")
    folder = folders[-1]
    metrics, yearly, _ = compute_metrics(load_run(folder))
    assert max(abs(v) for v in metrics["reconciliation"].values()) < 1e-6
    assert metrics["strategy_net"]["missing_days"] == 0
    assert metrics["strategy_net"]["notional_missing_days"] == 0

    manifest = json.loads((folder / "manifest.json").read_text())
    costs = json.loads((folder / "config.json").read_text())["run"]["costs"]
    m3_window = (
        manifest["data"]["first_trading_day"] == "2021-10-01"
        and manifest["data"]["last_trading_day"] == "2026-10-16"
    )
    if m3_window and (costs["brokerage_per_order_rs"], costs["slippage_points_per_leg"]) == (
        20.0,
        0.5,
    ):
        assert metrics["trades"]["trades"] == 263
        assert metrics["trades"]["net_rs"] == pytest.approx(279_138.515828, abs=1e-4)
        assert metrics["strategy_net"]["roi"] == pytest.approx(279_138.515828 / 500_000, abs=1e-9)
        # TRI on 1 Oct 2021 = 25,111.25 (niftyindices answer, traced by hand in M2).
        assert metrics["benchmark_nifty50_tri"]["tri_start"] == 25111.25
        assert yearly["trades"].sum() == 263


def test_api_serves_every_saved_run() -> None:
    """M5: every real run folder loads through the API without being invalid, and a run's
    metrics are served exactly as saved (here, the M4 reference totals)."""
    import json

    from fastapi.testclient import TestClient

    from nifty_backtest.api.app import create_app
    from nifty_backtest.api.settings import ApiSettings

    if not REPO_RUNS.is_dir():
        pytest.skip("no saved runs; run `nifty-backtest backtest`")
    client = TestClient(create_app(ApiSettings(runs_dir=REPO_RUNS)))
    runs = client.get("/api/runs").json()
    assert runs, "runs/ holds no run folders"
    assert {r["status"] for r in runs} <= {"complete", "metrics_missing"}
    for run in (r for r in runs if r["status"] == "complete"):
        served = client.get(f"/api/runs/{run['run_id']}/metrics").json()
        saved = json.loads((REPO_RUNS / run["run_id"] / "metrics.json").read_text())
        assert served == saved
        trades = client.get(f"/api/runs/{run['run_id']}/trades").json()
        assert sum(t["pnl_rs_net"] for t in trades) == pytest.approx(served["trades"]["net_rs"])
