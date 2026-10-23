"""Compute, save and print every spec §6 metric for a saved run.

Headline conventions (owner-approved for M4, decisions D1-D5):
- Sharpe/Sortino HEADLINE: daily return on notional, net of slippage and charges, target 0%.
  A short straddle never invests its notional, so its P&L per unit of notional is already an
  excess return; the 6.5% target versions are reported as clearly labelled SENSITIVITIES.
- Rupee Sharpe/Sortino and the TRI benchmark: daily return on previous-day equity, target 6.5%.
- Annualisation: 252 trading days (configurable).
- Trade t-statistics: on net % of premium collected (leading) and net points per unit; never
  on rupees, whose scale changes with the lot size. Net % of premium collected (M3 definition):
      pnl_pct_premium_net = 100 x pnl_points_net / premium_fill_points
      pnl_points_net      = pnl_rs_net / quantity
      premium_fill_points = sum over legs of (close - slippage)
- Win = net P&L > 0, loss < 0, exact zero counted separately (sign is the same in rupees,
  points and %, since quantity > 0).
- Gaps: a daily series with a missing value gets None for its Sharpe/Sortino, with the reason.

Missing-data rules (owner-approved M4 correction, R1-R5):
- R1 ROI, total P&L and CAGR use the capital and the equity on the run's LAST trading day. If
  that value is missing they are None with the reason; an earlier day is never used instead.
- R2 Max drawdown uses the observed days, running peak from the capital; with missing days it
  is flagged as an observed lower bound.
- R3 A monthly/yearly return needs both period boundaries (previous period's last day, or the
  capital, and its own last day); if either is missing it is None with the reason. A yearly
  drawdown with a missing start value starts from the first observed value (lower bound),
  never a silent 0.
- R4 The TRI benchmark goes through the same functions, so the same rules apply.
- R5 metrics.json is strict JSON: NaN and infinity are written as null.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from nifty_backtest.metrics.benchmark import BenchmarkError, tri_equity
from nifty_backtest.metrics.series import (
    RunData,
    load_run,
    notional_returns,
    rupee_gross,
    rupee_net,
    rupee_returns,
    sum_keep_gaps,
)
from nifty_backtest.metrics.stats import (
    Ratio,
    cagr,
    daily_rate,
    drawdown_series,
    max_drawdown,
    roi,
    sharpe,
    sortino,
    t_stat,
)


@dataclass(frozen=True)
class MetricsConfig:
    risk_free_rate: float = 0.065  # rupee series and benchmark; notional sensitivity
    notional_target_rate: float = 0.0  # headline notional Sharpe/Sortino (D1)
    periods_per_year: int = 252  # annualisation (D4)


def _ratio(r: Ratio) -> dict[str, Any]:
    return {"value": r.value, "note": r.note}


def _day(d: date | None) -> str | None:
    return None if d is None else d.isoformat()


def series_block(
    equity: pd.Series, notional: pd.Series | None, capital: float, cfg: MetricsConfig
) -> dict[str, Any]:
    """Return, drawdown and risk-adjusted metrics for one equity curve."""
    periods = cfg.periods_per_year
    rf = daily_rate(cfg.risk_free_rate, periods)
    days = list(equity.index)
    final = float(equity.iloc[-1])
    # R1: the totals need the last trading day's equity itself; never an earlier day's.
    final_missing = math.isnan(final)
    dd = max_drawdown(equity, capital)
    rupee = rupee_returns(equity, capital)
    block: dict[str, Any] = {
        "first_day": _day(days[0]),
        "last_day": _day(days[-1]),
        "final_equity_rs": None if final_missing else final,
        "total_pnl_rs": None if final_missing else final - capital,
        "roi": None if final_missing else roi(final, capital),
        "cagr": None if final_missing else cagr(capital, final, days[0], days[-1]),
        "totals_note": f"final equity missing on {_day(days[-1])}: total P&L, ROI and CAGR "
        "not computed"
        if final_missing
        else "",
        "max_drawdown_rs": dd.max_rs,
        "max_drawdown_rs_peak": _day(dd.rs_peak_date),
        "max_drawdown_rs_trough": _day(dd.rs_trough_date),
        "max_drawdown_rs_recovered": _day(dd.rs_recovery_date),
        "max_drawdown_pct": dd.max_pct,
        "max_drawdown_pct_peak": _day(dd.pct_peak_date),
        "max_drawdown_pct_trough": _day(dd.pct_trough_date),
        "max_drawdown_pct_recovered": _day(dd.pct_recovery_date),
        "max_drawdown_lower_bound": dd.lower_bound,
        "max_drawdown_note": dd.note,
        "missing_days": dd.missing_days,
        "sharpe_rupee": _ratio(sharpe(rupee, rf, periods)),
        "sortino_rupee": _ratio(sortino(rupee, rf, periods)),
    }
    if notional is not None:
        target = daily_rate(cfg.notional_target_rate, periods)
        block["sharpe_notional"] = _ratio(sharpe(notional, target, periods))
        block["sortino_notional"] = _ratio(sortino(notional, target, periods))
        block["sensitivity_sharpe_notional_at_rf"] = _ratio(sharpe(notional, rf, periods))
        block["sensitivity_sortino_notional_at_rf"] = _ratio(sortino(notional, rf, periods))
        block["notional_missing_days"] = int(notional.isna().sum())
    return block


def trade_block(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0}
    net = trades["pnl_rs_net"]
    wins, losses = trades[net > 0], trades[net < 0]

    def best_worst(column: str) -> dict[str, Any]:
        values = trades[column].to_numpy()
        best, worst = trades.iloc[int(values.argmax())], trades.iloc[int(values.argmin())]
        return {
            "best": float(best[column]),
            "best_trade": str(best["trade_id"]),
            "worst": float(worst[column]),
            "worst_trade": str(worst["trade_id"]),
        }

    def avg(frame: pd.DataFrame, column: str) -> float | None:
        return float(frame[column].mean()) if len(frame) else None

    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "zero_pnl": int((net == 0).sum()),
        "win_rate": len(wins) / len(trades),
        "avg_win_rs": avg(wins, "pnl_rs_net"),
        "avg_loss_rs": avg(losses, "pnl_rs_net"),
        "avg_win_points": avg(wins, "pnl_points_net"),
        "avg_loss_points": avg(losses, "pnl_points_net"),
        "avg_win_pct_premium": avg(wins, "pnl_pct_premium_net"),
        "avg_loss_pct_premium": avg(losses, "pnl_pct_premium_net"),
        "rs": best_worst("pnl_rs_net"),
        "points": best_worst("pnl_points_net"),
        "mean_pct_premium_net": float(trades["pnl_pct_premium_net"].mean()),
        "mean_points_net": float(trades["pnl_points_net"].mean()),
        "t_stat_pct_premium_net": t_stat(trades["pnl_pct_premium_net"].tolist()),
        "t_stat_points_net": t_stat(trades["pnl_points_net"].tolist()),
        "gross_rs": float(trades["pnl_rs_gross"].sum()),
        "slippage_rs": float(trades["slippage_rs"].sum()),
        "charges_rs": float(trades["charges_rs"].sum()),
        "net_rs": float(net.sum()),
        "charges_by_line_rs": {
            c.removesuffix("_rs"): float(trades[c].sum())
            for c in (
                "brokerage_rs",
                "stt_rs",
                "exchange_rs",
                "ipft_rs",
                "sebi_rs",
                "stamp_rs",
                "gst_rs",
            )
        },
    }


def _period_table(
    keys: pd.Series,
    equity: pd.Series,
    capital: float,
    benchmark: pd.Series | None,
) -> pd.DataFrame:
    """Start/end equity per period; each period starts from the previous period's end.

    R3: a period's P&L and return need both boundaries. If the start (the previous period's
    last day) or the end (this period's last day) is missing they are None, with the reason
    in `note`, so one missing month-end empties exactly that month and the next.
    """
    rows, start = [], capital
    bench_start = None if benchmark is None else capital
    previous_last: date | None = None
    for key in keys.unique():
        days = keys[keys == key].index
        end = float(equity.loc[days].iloc[-1])
        missing = []
        if math.isnan(start):
            missing.append(f"start equity missing ({_day(previous_last)})")
        if math.isnan(end):
            missing.append(f"end equity missing ({_day(days[-1])})")
        row: dict[str, Any] = {
            "period": key,
            "trading_days": len(days),
            "start_equity_rs": start,
            "end_equity_rs": end,
            "pnl_rs": None if missing else end - start,
            "return": None if missing else end / start - 1,
            "note": "; ".join(missing),
        }
        if benchmark is not None and bench_start is not None:
            bench_end = float(benchmark.loc[days].iloc[-1])
            known = not (math.isnan(bench_start) or math.isnan(bench_end))
            row["benchmark_return"] = bench_end / bench_start - 1 if known else None
            if not known:
                row["note"] = "; ".join([*missing, "benchmark boundary missing"])
            bench_start = bench_end
        rows.append(row)
        start, previous_last = end, days[-1]
    return _note_last(pd.DataFrame(rows))


def _note_last(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the explanatory `note` column at the end, after the numbers."""
    return frame[[c for c in frame.columns if c != "note"] + ["note"]]


def monthly_table(equity: pd.Series, capital: float, benchmark: pd.Series | None) -> pd.DataFrame:
    keys = pd.Series([f"{d:%Y-%m}" for d in equity.index], index=equity.index)
    return _period_table(keys, equity, capital, benchmark).rename(columns={"period": "month"})


def yearly_table(
    run: RunData,
    equity: pd.Series,
    notional: pd.Series,
    benchmark: pd.Series | None,
    cfg: MetricsConfig,
) -> pd.DataFrame:
    """Calendar-year breakdown. Trade statistics group trades by EXPIRY year (when the P&L is
    realised); daily statistics group days by date. Years the run only partly covers are
    flagged and their returns are NOT annualised."""
    keys = pd.Series([d.year for d in equity.index], index=equity.index)
    table = _period_table(keys, equity, run.capital, benchmark).rename(columns={"period": "year"})
    first, last = equity.index[0], equity.index[-1]
    periods = cfg.periods_per_year
    rf = daily_rate(cfg.risk_free_rate, periods)
    target = daily_rate(cfg.notional_target_rate, periods)
    rupee = rupee_returns(equity, run.capital)
    extra = []
    for _, row in table.iterrows():
        year = int(row["year"])
        days = keys[keys == year].index
        trades = run.trades[[e.year == year for e in run.trades["expiry"]]]
        dd = max_drawdown(equity.loc[days], float(row["start_equity_rs"]))
        extra.append(
            {
                "partial_year": first > date(year, 1, 1) or last < date(year, 12, 31),
                "trades": len(trades),
                "win_rate": float((trades["pnl_rs_net"] > 0).mean()) if len(trades) else None,
                "net_rs_by_expiry": float(trades["pnl_rs_net"].sum()),
                "net_points_by_expiry": float(trades["pnl_points_net"].sum()),
                "mean_pct_premium_net": float(trades["pnl_pct_premium_net"].mean())
                if len(trades)
                else None,
                "t_stat_pct_premium_net": t_stat(trades["pnl_pct_premium_net"].tolist()),
                "t_stat_points_net": t_stat(trades["pnl_points_net"].tolist()),
                "max_drawdown_rs": dd.max_rs,
                "max_drawdown_pct": dd.max_pct,
                "max_drawdown_lower_bound": dd.lower_bound,
                "sharpe_notional": sharpe(notional.loc[days], target, periods).value,
                "sortino_notional": sortino(notional.loc[days], target, periods).value,
                "sharpe_rupee": sharpe(rupee.loc[days], rf, periods).value,
            }
        )
    return _note_last(pd.concat([table, pd.DataFrame(extra)], axis=1))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_tri(run: RunData) -> tuple[pd.Series, Path]:
    """NIFTY 50 TRI by date from the run's own index data file (and that file's path)."""
    index_file = Path(run.config["run"]["data"]["data_dir"]) / "processed" / "index_daily.parquet"
    index = pd.read_parquet(index_file)
    tri = pd.Series(index["nifty_tri"].to_numpy(), index=pd.to_datetime(index["date"]).dt.date)
    return tri, index_file


def daily_table(run: RunData) -> pd.DataFrame:
    """The daily series behind the dashboard's charts (M6), saved as daily.csv.

    Built only from functions the metrics already use: the net and gross equity curves, the
    TRI buy-and-hold curve, and drawdown_series (the same peak rule as max_drawdown). Missing
    values stay missing. If the benchmark cannot be computed, its columns are empty and
    metrics.json says why.
    """
    net, gross = rupee_net(run), rupee_gross(run)
    net_drawdown = drawdown_series(net, run.capital)
    try:
        benchmark = tri_equity(load_tri(run)[0], run.days, run.capital)
    except (BenchmarkError, FileNotFoundError, KeyError):
        benchmark = pd.Series(math.nan, index=run.days)
    return pd.DataFrame(
        {
            "date": run.days,
            "equity_net_rs": net.to_numpy(),
            "equity_gross_rs": gross.to_numpy(),
            "drawdown_net_rs": net_drawdown["drawdown_rs"].to_numpy(),
            "drawdown_net_pct": net_drawdown["drawdown_pct"].to_numpy(),
            "benchmark_equity_rs": benchmark.to_numpy(),
            "benchmark_drawdown_pct": drawdown_series(benchmark, run.capital)[
                "drawdown_pct"
            ].to_numpy(),
        }
    )


def compute_metrics(
    run: RunData, cfg: MetricsConfig | None = None
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """All metrics for a saved run: (metrics dict, yearly table, monthly table)."""
    cfg = cfg or MetricsConfig()
    net_equity, gross_equity = rupee_net(run), rupee_gross(run)
    notional_net = notional_returns(run, net=True)
    notional_gross = notional_returns(run, net=False)

    # Benchmark: the run's own index data file, checked against the hash in its manifest.
    benchmark: pd.Series | None = None
    benchmark_block: dict[str, Any]
    try:
        tri, index_file = load_tri(run)
        benchmark = tri_equity(tri, run.days, run.capital)
        benchmark_block = series_block(benchmark, None, run.capital, cfg)
        benchmark_block["tri_start"] = float(tri[run.days[0]])
        benchmark_block["tri_end"] = float(tri[run.days[-1]])
        benchmark_block["index_data_matches_run"] = (
            _sha256(index_file) == run.manifest["data"]["index_data_sha256"]
        )
    except (BenchmarkError, FileNotFoundError, KeyError) as exc:
        benchmark_block = {"not_computed": str(exc)}

    trades = trade_block(run.trades)
    yearly = yearly_table(run, net_equity, notional_net, benchmark, cfg)
    monthly = monthly_table(net_equity, run.capital, benchmark)
    total_net = float(net_equity.iloc[-1]) - run.capital
    # Each check should be ~0 (floating-point noise only). A check that would need a missing
    # value is NaN (null in metrics.json): it cannot be done, and pandas' default sum, which
    # skips NaN, would report a misleading mismatch instead.
    reconciliation = {
        "gross_minus_slippage_minus_charges_minus_net": trades.get("gross_rs", 0.0)
        - trades.get("slippage_rs", 0.0)
        - trades.get("charges_rs", 0.0)
        - trades.get("net_rs", 0.0),
        "final_equity_minus_capital_minus_trade_net": total_net - trades.get("net_rs", 0.0),
        "yearly_net_by_expiry_minus_total": float(yearly["net_rs_by_expiry"].sum()) - total_net,
        "yearly_pnl_by_date_minus_total": sum_keep_gaps(yearly["pnl_rs"]) - total_net,
        "monthly_pnl_minus_total": sum_keep_gaps(monthly["pnl_rs"]) - total_net,
        "notional_daily_sum_minus_trade_sum": sum_keep_gaps(notional_net)
        - float((run.trades["pnl_points_net"] / run.trades["nifty_close_at_entry"]).sum())
        if not run.trades.empty
        else 0.0,
    }
    # R5: None, never NaN or infinity, for every consumer (metrics.json, the CLI, the API).
    metrics: dict[str, Any] = strict_json(
        {
            "run_id": run.manifest.get("run_id"),
            "git": run.manifest.get("git"),
            "metrics_config": asdict(cfg),
            "capital_rs": run.capital,
            "strategy_net": series_block(net_equity, notional_net, run.capital, cfg),
            "strategy_gross": series_block(gross_equity, notional_gross, run.capital, cfg),
            "benchmark_nifty50_tri": benchmark_block,
            "trades": trades,
            "reconciliation": reconciliation,
        }
    )
    return metrics, yearly, monthly


def _fmt(value: Any, kind: str = "num") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, dict):
        return _fmt(value.get("value"), kind) + (f" ({value['note']})" if value.get("note") else "")
    if kind == "pct":
        return f"{value * 100:.2f}%"
    if kind == "rs":
        return f"Rs {value:,.2f}"
    return f"{value:.2f}"


def summary_text(metrics: dict[str, Any]) -> str:
    net, gross = metrics["strategy_net"], metrics["strategy_gross"]
    bench, t = metrics["benchmark_nifty50_tri"], metrics["trades"]
    git = metrics.get("git") or {}
    dirty = ", UNCOMMITTED CHANGES" if git.get("uncommitted_changes") else ""
    lines = [
        f"Run {metrics['run_id']}  ({net['first_day']} to {net['last_day']}, "
        f"capital Rs {metrics['capital_rs']:,.0f}, git {str(git.get('commit'))[:7]}{dirty})",
        "",
        f"{'':34}{'net':>18}{'gross (no costs)':>20}{'NIFTY 50 TRI':>18}",
    ]

    def row(label: str, key: str, kind: str) -> str:
        b = _fmt(bench.get(key), kind) if "not_computed" not in bench else "n/a"
        return f"{label:34}{_fmt(net.get(key), kind):>18}{_fmt(gross.get(key), kind):>20}{b:>18}"

    lines += [
        row("Total P&L", "total_pnl_rs", "rs"),
        row("ROI (on starting capital)", "roi", "pct"),
        row("CAGR", "cagr", "pct"),
        row("Max drawdown (Rs)", "max_drawdown_rs", "rs"),
        row("Max drawdown (%)", "max_drawdown_pct", "pct"),
        row("Sharpe, notional, 0% [HEADLINE]", "sharpe_notional", "num"),
        row("Sortino, notional, 0% [HEADLINE]", "sortino_notional", "num"),
        row("Sharpe, rupee, 6.5%", "sharpe_rupee", "num"),
        row("Sortino, rupee, 6.5%", "sortino_rupee", "num"),
        row("[sensitivity] Sharpe notional @6.5%", "sensitivity_sharpe_notional_at_rf", "num"),
        row("[sensitivity] Sortino notional @6.5%", "sensitivity_sortino_notional_at_rf", "num"),
        "",
        f"Trades {t['trades']}: {t['wins']} wins, {t['losses']} losses, {t['zero_pnl']} zero; "
        f"win rate {t['win_rate'] * 100:.1f}%",
        f"Mean net % of premium {t['mean_pct_premium_net']:.2f}% "
        f"(t = {_fmt(t['t_stat_pct_premium_net'])}); "
        f"mean net points/unit {t['mean_points_net']:.2f} (t = {_fmt(t['t_stat_points_net'])})",
        f"Avg win {_fmt(t['avg_win_rs'], 'rs')} / avg loss {_fmt(t['avg_loss_rs'], 'rs')}; "
        f"best {_fmt(t['rs']['best'], 'rs')} ({t['rs']['best_trade']}), "
        f"worst {_fmt(t['rs']['worst'], 'rs')} ({t['rs']['worst_trade']})",
        f"Gross {_fmt(t['gross_rs'], 'rs')} - slippage {_fmt(t['slippage_rs'], 'rs')} - charges "
        f"{_fmt(t['charges_rs'], 'rs')} = net {_fmt(t['net_rs'], 'rs')}",
    ]
    for label, block in (("net", net), ("gross", gross), ("TRI", bench)):
        for key in ("totals_note", "max_drawdown_note"):
            if block.get(key):
                lines.append(f"Note ({label}): {block[key]}")
    checks = [v for v in metrics["reconciliation"].values() if _finite(v)]
    skipped = len(metrics["reconciliation"]) - len(checks)
    worst_gap = max((abs(v) for v in checks), default=0.0)
    lines.append(
        f"Reconciliation: largest mismatch Rs {worst_gap:.2e} (all checks should be ~0)"
        + (f"; {skipped} checks not possible (missing data)" if skipped else "")
    )
    return "\n".join(lines)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def strict_json(value: Any) -> Any:
    """R5: replace NaN and infinity with None (JSON null), recursively. Python's json module
    would otherwise write the non-standard tokens NaN / Infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: strict_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict_json(v) for v in value]
    return value


def markdown_table(frame: pd.DataFrame) -> str:
    """A DataFrame as a Markdown table (pandas' own needs an extra package)."""

    def cell(v: Any) -> str:
        if isinstance(v, float):
            return "" if pd.isna(v) else f"{v:,.4f}"
        return "" if v is None else str(v)

    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def write_metrics(folder: Path, cfg: MetricsConfig | None = None) -> dict[str, Any]:
    """Compute metrics for a saved run and write metrics.json, yearly.csv, monthly.csv,
    daily.csv (M6) and summary.md next to its trade log."""
    run = load_run(folder)
    metrics, yearly, monthly = compute_metrics(run, cfg)
    daily_table(run).to_csv(folder / "daily.csv", index=False)
    # allow_nan=False: fail loudly rather than ever write NaN into the file.
    (folder / "metrics.json").write_text(
        json.dumps(metrics, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )
    yearly.to_csv(folder / "yearly.csv", index=False)
    monthly.to_csv(folder / "monthly.csv", index=False)
    (folder / "summary.md").write_text(
        "# Backtest summary\n\n```\n"
        + summary_text(metrics)
        + "\n```\n\n## Calendar years\n\n"
        + markdown_table(yearly)
        + "\n",
        encoding="utf-8",
    )
    return metrics
