"""Metrics on a saved run: series, benchmark, gaps, reconciliation and the D6 run-saving fixes.

Uses the hand-built week from test_engine.py (entry Mon 4 Aug 2025 at NIFTY 25,020, lot 75,
net P&L Rs 8,852.28050405, entry charges Rs 70.51584595). Net P&L per unit by day
(net rupee mark / 75): Mon -1.94021128, Tue 18.05978872, Wed 28.05978872, Thu 118.03040672.
"""

import json
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nifty_backtest.engine import runs
from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.indices import index_path
from nifty_backtest.metrics.benchmark import BenchmarkError, tri_equity
from nifty_backtest.metrics.series import (
    RunData,
    load_run,
    notional_returns,
    rupee_gross,
    rupee_net,
    rupee_returns,
)
from nifty_backtest.metrics.summary import (
    MetricsConfig,
    compute_metrics,
    monthly_table,
    series_block,
    write_metrics,
    yearly_table,
)
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.test_engine import MON, THU, TUE, WED, setup, week

ENTRY_LEVEL = 25020.0
NET_PER_UNIT = [-1.94021128, 18.05978872, 28.05978872, 118.03040672]


def saved_run(cfg: DataConfig, tmp_path: Path) -> Path:
    run = setup(cfg, tmp_path, week())
    return runs.save_run(
        run_backtest(run, ShortStraddle()), run, ShortStraddle(), runs_dir=tmp_path / "runs"
    )


def test_notional_returns_hand_computed(cfg: DataConfig, tmp_path: Path) -> None:
    run = load_run(saved_run(cfg, tmp_path))
    net = notional_returns(run, net=True)
    # Day change in net P&L per unit / 25,020. Mon: -1.94021128 (entry slippage + charges);
    # Tue: +20; Wed: +10; Thu: 118.03040672 - 28.05978872 = 89.97061800.
    expected = [NET_PER_UNIT[0], 20.0, 10.0, NET_PER_UNIT[3] - NET_PER_UNIT[2]]
    assert net.tolist() == pytest.approx([x / ENTRY_LEVEL for x in expected])
    # The days add up to the trade's net points per unit over its entry level.
    assert net.sum() == pytest.approx(8852.28050405 / 75 / ENTRY_LEVEL)
    # Gross: no slippage or charges, so Mon is exactly 0 and Thu is 120 - 30 = 90.
    gross = notional_returns(run, net=False)
    assert gross.tolist() == pytest.approx(
        [0.0, 20 / ENTRY_LEVEL, 10 / ENTRY_LEVEL, 90 / ENTRY_LEVEL]
    )


def test_rupee_series_hand_computed(cfg: DataConfig, tmp_path: Path) -> None:
    run = load_run(saved_run(cfg, tmp_path))
    # Gross equity: (220 - value) x 75 while open, Rs 9,000 realised on Thu.
    assert rupee_gross(run).tolist() == pytest.approx([500_000, 501_500, 502_250, 509_000])
    net = rupee_net(run)
    returns = rupee_returns(net, 500_000)
    # First day measured against capital; later days against the previous day's equity.
    assert returns.iloc[0] == pytest.approx(net.iloc[0] / 500_000 - 1)
    assert returns.iloc[2] == pytest.approx(net.iloc[2] / net.iloc[1] - 1)


def test_metrics_reconcile_and_benchmark_uses_tri(cfg: DataConfig, tmp_path: Path) -> None:
    metrics, yearly, monthly = compute_metrics(load_run(saved_run(cfg, tmp_path)))
    assert max(abs(v) for v in metrics["reconciliation"].values()) < 1e-6
    net = metrics["strategy_net"]
    assert net["total_pnl_rs"] == pytest.approx(8852.28050405)
    assert net["roi"] == pytest.approx(8852.28050405 / 500_000)
    # The helper's TRI is 1.4 x the NIFTY close: 25,020 -> 24,900 is a -0.4796% move.
    bench = metrics["benchmark_nifty50_tri"]
    assert bench["roi"] == pytest.approx(24900 / 25020 - 1)
    assert bench["index_data_matches_run"] is True
    trades = metrics["trades"]
    assert (trades["trades"], trades["wins"], trades["t_stat_pct_premium_net"]) == (1, 1, None)
    assert yearly["year"].tolist() == [2025]
    assert monthly["month"].tolist() == ["2025-08"]


def test_a_missing_mark_nulls_the_daily_ratios_but_not_the_totals(
    cfg: DataConfig, tmp_path: Path
) -> None:
    folder = saved_run(cfg, tmp_path)
    marks = pd.read_csv(folder / "marks.csv")
    marks.loc[marks["date"] == TUE.isoformat(), "mtm_rs_net"] = float("nan")
    marks.to_csv(folder / "marks.csv", index=False)
    equity = pd.read_csv(folder / "equity.csv")
    equity.loc[equity["date"] == TUE.isoformat(), "equity_rs"] = float("nan")
    equity.to_csv(folder / "equity.csv", index=False)

    metrics, _, _ = compute_metrics(load_run(folder))
    net = metrics["strategy_net"]
    for key in ("sharpe_notional", "sortino_notional", "sharpe_rupee", "sortino_rupee"):
        assert net[key]["value"] is None
        assert "missing" in net[key]["note"]
    assert net["notional_missing_days"] == 2  # Tue itself and Wed's change from Tue
    assert net["roi"] == pytest.approx(8852.28050405 / 500_000)  # endpoints are intact


def test_benchmark_coverage_rules() -> None:
    days = [MON, TUE, WED, THU]
    tri = pd.Series([100.0, 110.0, 99.0, 121.0], index=days)
    assert tri_equity(tri, days, 1000.0).tolist() == pytest.approx([1000, 1100, 990, 1210])
    gappy = tri_equity(tri.drop(TUE), days, 1000.0)  # interior gap: kept missing, not filled
    assert pd.isna(gappy[TUE])
    with pytest.raises(BenchmarkError):
        tri_equity(tri.drop(THU), days, 1000.0)  # no TRI on the last day: no benchmark


def test_months_chain_across_a_year_boundary() -> None:
    days = [date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 2)]
    equity = pd.Series([1010.0, 1020.0, 1015.0, 1030.0], index=days)
    table = monthly_table(equity, 1000.0, None)
    assert table["month"].tolist() == ["2024-12", "2025-01"]
    # Dec: 1000 -> 1020 = +2%; Jan starts from Dec's end: 1020 -> 1030.
    assert table["return"].tolist() == pytest.approx([0.02, 1030 / 1020 - 1])


def test_saved_config_records_the_resolved_end_date(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week())
    open_ended = replace(run, data=replace(run.data, end=None))
    folder = runs.save_run(
        run_backtest(run, ShortStraddle()),
        open_ended,
        ShortStraddle(),
        runs_dir=tmp_path / "runs",
        today=date(2025, 8, 7),
    )
    saved = json.loads((folder / "config.json").read_text())
    assert saved["run"]["data"]["end"] == "2025-08-07"  # not null


def test_saving_from_a_dirty_tree_warns(
    cfg: DataConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        runs, "_git_state", lambda: {"commit": "abc1234", "uncommitted_changes": True}
    )
    with caplog.at_level(logging.WARNING):
        saved_run(cfg, tmp_path)
    assert "uncommitted changes" in caplog.text


def test_write_metrics_creates_the_files(cfg: DataConfig, tmp_path: Path) -> None:
    folder = saved_run(cfg, tmp_path)
    write_metrics(folder)
    for name in ("metrics.json", "yearly.csv", "monthly.csv", "summary.md"):
        assert (folder / name).exists()
    assert "HEADLINE" in (folder / "summary.md").read_text()


# --- Missing-data rules R1-R5 (M4 correction). Each test reproduces a defect found by probing
# the original M4 code, which returned NaN without a reason, wrote NaN into metrics.json, or
# reported a zero drawdown.

NAN = float("nan")
JAN30, JAN31, FEB3, FEB4 = date(2025, 1, 30), date(2025, 1, 31), date(2025, 2, 3), date(2025, 2, 4)


def test_missing_final_equity_nulls_the_totals_with_a_reason() -> None:
    # R1: 100 -> 110 -> 90 -> (missing). The old code returned NaN; falling back to 90 would
    # silently shorten the period. Both are wrong: the totals are None, with the reason.
    equity = pd.Series([100.0, 110.0, 90.0, NAN], index=[JAN30, JAN31, FEB3, FEB4])
    block = series_block(equity, None, 100.0, MetricsConfig())
    for key in ("final_equity_rs", "total_pnl_rs", "roi", "cagr"):
        assert block[key] is None
    assert block["totals_note"] == (
        "final equity missing on 2025-02-04: total P&L, ROI and CAGR not computed"
    )
    # R2: drawdown over the observed days, 110 -> 90 = Rs 20, flagged as a lower bound.
    assert block["max_drawdown_rs"] == pytest.approx(20.0)
    assert block["max_drawdown_lower_bound"] is True


def test_an_interior_gap_keeps_the_totals_and_flags_the_drawdown() -> None:
    # R1: only the last day matters for the totals: 100 -> 105 is +5%.
    equity = pd.Series([100.0, NAN, 90.0, 105.0], index=[JAN30, JAN31, FEB3, FEB4])
    block = series_block(equity, None, 100.0, MetricsConfig())
    assert (block["total_pnl_rs"], block["roi"], block["totals_note"]) == (5.0, 0.05, "")
    assert block["cagr"] is not None
    assert block["max_drawdown_rs"] == pytest.approx(10.0)  # 100 (capital) -> 90
    assert block["max_drawdown_lower_bound"] is True
    assert block["max_drawdown_note"] == "observed lower bound: 1 daily values missing"
    assert block["missing_days"] == 1


def test_a_missing_month_end_nulls_that_month_and_the_next_only() -> None:
    # R3: Jan's end (31 Jan) is missing, so Jan has no end and Feb has no start. March starts
    # from Feb's known end again: 105 -> 126 = +20%.
    days = [JAN30, JAN31, FEB3, date(2025, 2, 28), date(2025, 3, 3)]
    equity = pd.Series([100.0, NAN, 90.0, 105.0, 126.0], index=days)
    table = monthly_table(equity, 100.0, None)
    assert table["month"].tolist() == ["2025-01", "2025-02", "2025-03"]
    assert table["note"].tolist() == [
        "end equity missing (2025-01-31)",
        "start equity missing (2025-01-31)",
        "",
    ]
    assert table["return"].isna().tolist() == [True, True, False]
    assert table["pnl_rs"].isna().tolist() == [True, True, False]
    assert table["return"].iloc[2] == pytest.approx(0.20)
    assert table.columns[-1] == "note"


def test_a_missing_year_start_never_reports_a_zero_drawdown() -> None:
    # R3, regression: 31 Dec 2024 equity is missing, so 2025 has no start value. The old
    # yearly table passed NaN as the drawdown's start and reported 0 for a 120 -> 80 fall.
    days = [date(2024, 12, 30), date(2024, 12, 31), date(2025, 1, 1), date(2025, 1, 2)]
    values = [100.0, NAN, 120.0, 80.0]
    trades = pd.DataFrame(
        {
            "expiry": [date(2025, 1, 2)],
            "pnl_rs_net": [-20.0],
            "pnl_points_net": [-1.0],
            "pnl_pct_premium_net": [-5.0],
        }
    )
    run = RunData(
        folder=Path("."),
        trades=trades,
        marks=pd.DataFrame(),
        equity=pd.DataFrame({"date": days, "equity_rs": values}),
        capital=100.0,
        config={},
        manifest={},
    )
    equity = pd.Series(values, index=days)
    notional = pd.Series(0.0, index=days)
    table = yearly_table(run, equity, notional, None, MetricsConfig()).set_index("year")
    assert table.loc[2024, "note"] == "end equity missing (2024-12-31)"
    assert table.loc[2025, "note"] == "start equity missing (2024-12-31)"
    assert pd.isna(table.loc[2024, "return"])
    assert pd.isna(table.loc[2025, "return"])
    assert table.loc[2025, "max_drawdown_rs"] == pytest.approx(40.0)
    assert table.loc[2025, "max_drawdown_lower_bound"]


def test_a_tri_gap_follows_the_same_rules(cfg: DataConfig, tmp_path: Path) -> None:
    # R4: TRI missing on Tue. Its end points are intact, so the benchmark's ROI still holds,
    # but its daily ratios are None and its drawdown is a lower bound.
    folder = saved_run(cfg, tmp_path)
    index_file = index_path(cfg)
    index = pd.read_parquet(index_file)
    index.loc[pd.to_datetime(index["date"]).dt.date == TUE, "nifty_tri"] = NAN
    index.to_parquet(index_file, index=False)

    metrics, _, monthly = compute_metrics(load_run(folder))
    bench = metrics["benchmark_nifty50_tri"]
    assert bench["roi"] == pytest.approx(24900 / 25020 - 1)
    assert bench["missing_days"] == 1
    assert bench["max_drawdown_lower_bound"] is True
    assert bench["sharpe_rupee"]["value"] is None
    assert bench["index_data_matches_run"] is False  # the file was changed after the run
    assert monthly["benchmark_return"].iloc[0] == pytest.approx(24900 / 25020 - 1)


def test_metrics_json_is_strict_json_with_nulls(cfg: DataConfig, tmp_path: Path) -> None:
    # R5, regression: with the last day's equity missing the old writer put a bare NaN
    # (not valid JSON) into metrics.json.
    folder = saved_run(cfg, tmp_path)
    equity = pd.read_csv(folder / "equity.csv")
    equity.loc[equity["date"] == THU.isoformat(), "equity_rs"] = NAN
    equity.to_csv(folder / "equity.csv", index=False)

    write_metrics(folder)
    text = (folder / "metrics.json").read_text()

    def reject(token: str) -> None:
        raise AssertionError(f"non-standard JSON token {token}")

    saved = json.loads(text, parse_constant=reject)
    assert saved["strategy_net"]["roi"] is None
    assert "final equity missing" in saved["strategy_net"]["totals_note"]
    assert saved["reconciliation"]["final_equity_minus_capital_minus_trade_net"] is None
    assert "checks not possible" in (folder / "summary.md").read_text()
