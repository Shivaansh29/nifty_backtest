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
from nifty_backtest.metrics.benchmark import BenchmarkError, tri_equity
from nifty_backtest.metrics.series import (
    load_run,
    notional_returns,
    rupee_gross,
    rupee_net,
    rupee_returns,
)
from nifty_backtest.metrics.summary import compute_metrics, monthly_table, write_metrics
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
