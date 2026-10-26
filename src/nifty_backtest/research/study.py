"""Run a pre-registered study and write its results (M7).

    nifty-backtest study docs/research/m7_plan.toml

1. Check the plan and the pre-registration are committed and unchanged (the study records
   their commit and SHA-256): results can only come AFTER the plan.
2. Run every variant in every period as a normal saved run (studies/<id>/runs/<run_id>/),
   then the cost grid for the baseline.
3. Pair each variant with the baseline expiry by expiry, compute the pre-registered
   statistics and apply the frozen decision rule (analysis.py). Variants the rule marks
   promising on development then get their own cost grid.
4. Write study.json, comparison.csv, families.csv (sensitivity grids), cost_grid.csv,
   regimes.csv and report.md.

The validation period ends where the plan says (16 Oct 2026), so newer data is never read.
"""

import hashlib
import json
import math
import subprocess
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.events import knowable_events_between, load_events
from nifty_backtest.marketdata.indicators import previous_session
from nifty_backtest.marketdata.indices import index_path
from nifty_backtest.metrics.summary import strict_json, write_metrics
from nifty_backtest.research.analysis import (
    PROMISING,
    compare,
    describe,
    development_verdict,
    edge_verdict,
    final_status,
    pair,
    validation_verdict,
)
from nifty_backtest.research.plan import Period, StudyPlan, Variant, load_plan, run_config
from nifty_backtest.research.stats import holm


class StudyError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def plan_git_state(paths: list[Path]) -> dict[str, Any]:
    """HEAD, the commit that last changed each file, and whether any has uncommitted edits."""
    return {
        "head": _git("rev-parse", "HEAD"),
        "files": {
            str(p): {"last_commit": _git("log", "-1", "--format=%H", "--", str(p))} for p in paths
        },
        "uncommitted_changes": bool(_git("status", "--porcelain", "--", *map(str, paths))),
    }


def _wait_for_new_second(previous: str | None) -> None:
    # Run ids have one-second resolution; never let two runs share one.
    while previous is not None and f"{datetime.now():%Y%m%d-%H%M%S}" == previous:
        time.sleep(0.05)


class Runner:
    """Runs variants into one study folder and remembers every run."""

    def __init__(
        self, runs_dir: Path, data: DataConfig, costs: CostConfig, log: Callable[[str], None]
    ):
        self.runs_dir, self.data, self.costs, self.log = runs_dir, data, costs, log
        self.records: list[dict[str, Any]] = []
        self.trades: dict[tuple[str, str], pd.DataFrame] = {}
        self._last_id: str | None = None

    def run(self, key: str, settings: dict[str, Any], period: Period, variant: Variant) -> None:
        cfg, strategy = run_config(settings, period, self.data, self.costs)
        result = run_backtest(cfg, strategy)
        _wait_for_new_second(self._last_id)
        folder = save_run(result, cfg, strategy, self.runs_dir)
        self._last_id = folder.name[:15]
        if not result.trades.empty:
            write_metrics(folder)
        self.trades[(key, period.name)] = result.trades
        self.records.append(
            {
                "key": key,
                "variant": variant.id,
                "role": variant.role,
                "of": variant.of,
                "period": period.name,
                "run_id": folder.name,
                "trades": len(result.trades),
                "skipped": len(result.skipped),
                "settings": settings,
            }
        )
        self.log(f"{key:18s} {period.name:12s} {len(result.trades):4d} trades  -> {folder.name}")

    def metrics(self, key: str, period: str) -> dict[str, Any] | None:
        record = self.record(key, period)
        path = self.runs_dir / record["run_id"] / "metrics.json"
        return json.loads(path.read_text()) if path.exists() else None

    def record(self, key: str, period: str) -> dict[str, Any]:
        return next(r for r in self.records if r["key"] == key and r["period"] == period)


def _changed(settings: dict[str, Any], base: dict[str, Any]) -> str:
    return ", ".join(f"{k}={settings[k]}" for k in settings if settings[k] != base[k]) or "baseline"


def _run_summary(runner: Runner, key: str, period: str) -> dict[str, Any]:
    """Headline numbers of one run, straight from its metrics.json (None if no trades)."""
    m = runner.metrics(key, period)
    trades = runner.trades[(key, period)]
    if m is None:
        return {"trades": 0, "net_pnl_rs": 0.0, "max_drawdown_pct": 0.0}
    net, gross, t = m["strategy_net"], m["strategy_gross"], m["trades"]
    bench = m["benchmark_nifty50_tri"]
    exits: dict[str, int] = {}
    for kind in ("ce", "pe"):
        column = f"{kind}_exit_reason"
        if column in trades:
            for reason in ("stop", "take_profit"):
                exits[f"{reason}_exits"] = exits.get(f"{reason}_exits", 0) + int(
                    (trades[column] == reason).sum()
                )
    return {
        "trades": t["trades"],
        "win_rate": t["win_rate"],
        "net_pnl_rs": net["total_pnl_rs"],
        "gross_pnl_rs": gross["total_pnl_rs"],
        "roi": net["roi"],
        "cagr": net["cagr"],
        "max_drawdown_pct": net["max_drawdown_pct"],
        "max_drawdown_rs": net["max_drawdown_rs"],
        "sharpe_notional": net["sharpe_notional"]["value"],
        "sortino_notional": net["sortino_notional"]["value"],
        "sharpe_rupee": net["sharpe_rupee"]["value"],
        "sortino_rupee": net["sortino_rupee"]["value"],
        "tri_roi": bench.get("roi"),
        "mean_pct_premium_executed": t["mean_pct_premium_net"],
        "t_pct_premium_executed": t["t_stat_pct_premium_net"],
        "avg_win_rs": t["avg_win_rs"],
        "avg_loss_rs": t["avg_loss_rs"],
        "worst_trade_rs": t["rs"]["worst"],
        "charges_rs": t["charges_rs"],
        "exit_charges_rs": float(trades["exit_charges_rs"].sum())
        if "exit_charges_rs" in trades
        else 0.0,
        **exits,
    }


def _families(plan: StudyPlan) -> list[tuple[str, str, list[Variant]]]:
    """(root variant, varying setting, members sorted by that setting) for every sensitivity
    family: a primary or realism variant with the variants declared `of` it, plus the
    entry-timing family around the baseline."""
    families = []
    for root in plan.variants:
        if root.role not in ("primary", "realism") or root.of is not None:
            continue
        by_setting: dict[str, list[Variant]] = {}
        for child in (c for c in plan.variants if c.of == root.id):
            (setting,) = [k for k in child.settings if child.settings[k] != root.settings[k]]
            by_setting.setdefault(setting, []).append(child)
        for setting, children in sorted(by_setting.items()):
            group = sorted([root, *children], key=lambda m: m.settings[setting])
            families.append((root.id, setting, group))
    entry = [plan.baseline, *(v for v in plan.variants if v.role == "descriptive")]
    entry.sort(key=lambda m: m.settings["entry_days_before_expiry"])
    families.append(("B0", "entry_days_before_expiry", entry))
    return families


def _regimes(plan: StudyPlan, runner: Runner, data: DataConfig) -> list[dict[str, Any]]:
    """Descriptive: the baseline by VIX(t-1) tercile and by event week, in each period."""
    index = pd.read_parquet(index_path(data))
    index["date"] = pd.to_datetime(index["date"]).dt.date
    vix = dict(zip(index["date"], index["vix_close"], strict=True))
    days = sorted(vix)
    events = load_events(data)
    low, high = plan.thresholds["vix_p33"], plan.thresholds["vix_p67"]
    rows = []
    for period in plan.periods:
        trades = runner.trades[("B0", period.name)].copy()
        if trades.empty:
            continue
        groups: dict[tuple[str, str], list[int]] = {}
        for i, (entry_text, expiry_text, tagged) in enumerate(
            zip(trades["entry_date"], trades["expiry"], trades["event_in_window"], strict=True)
        ):
            entry, expiry = (
                date.fromisoformat(str(entry_text)[:10]),
                date.fromisoformat(str(expiry_text)[:10]),
            )
            info = previous_session(days, entry)
            level = vix.get(info) if info else None
            if level is None or pd.isna(level):
                tercile = "unknown"
            else:
                tercile = "low" if level < low else ("high" if level >= high else "middle")
            known = bool(info and knowable_events_between(events, entry, expiry, info))
            for grouping, group in (
                ("vix_tercile", tercile),
                ("any_event_in_window", str(bool(tagged))),
                ("knowable_scheduled_event", str(known)),
            ):
                groups.setdefault((grouping, group), []).append(i)
        for (grouping, group), positions in sorted(groups.items()):
            part = trades.iloc[positions]
            rows.append(
                {
                    "period": period.name,
                    "grouping": grouping,
                    "group": group,
                    "trades": len(part),
                    "mean_pct_premium_net": float(part["pnl_pct_premium_net"].mean()),
                    "total_net_rs": float(part["pnl_rs_net"].sum()),
                    "win_rate": float((part["pnl_rs_net"] > 0).mean()),
                }
            )
    return rows


def run_study(
    plan_path: Path,
    preregistration_path: Path,
    data: DataConfig,
    costs: CostConfig,
    studies_dir: Path = Path("studies"),
    require_committed: bool = True,
    log: Callable[[str], None] = print,
) -> Path:
    plan = load_plan(plan_path)
    git = plan_git_state([plan_path, preregistration_path])
    if require_committed and (
        git["uncommitted_changes"] or not all(f["last_commit"] for f in git["files"].values())
    ):
        raise StudyError(
            "the study plan and pre-registration must be committed, unchanged, before any "
            "variant runs"
        )
    study_id = f"{datetime.now():%Y%m%d-%H%M%S}-{plan.name}"
    folder = studies_dir / study_id
    runner = Runner(folder / "runs", data, costs, log)
    base = plan.baseline.settings

    for variant in plan.variants:
        for period in plan.periods:
            runner.run(variant.id, variant.settings, period, variant)

    def grid(variant: Variant) -> None:
        for slip in plan.grid_slippage:
            for brokerage in plan.grid_brokerage:
                settings = variant.settings | {
                    "slippage_points_per_leg": slip,
                    "brokerage_per_order_rs": brokerage,
                }
                if settings == variant.settings:
                    continue  # the variant itself is the grid's own cell
                key = f"{variant.id}@slip{slip:g}-brk{brokerage:g}"
                for period in plan.periods:
                    runner.run(key, settings, period, variant)

    grid(plan.baseline)

    # --- comparisons --------------------------------------------------------------------
    def comparison(key: str, period: Period) -> dict[str, Any]:
        pairing = pair(runner.trades[("B0", period.name)], runner.trades[(key, period.name)])
        return compare(pairing, plan.seed, plan.resamples, plan.block_length)

    dev, val = plan.periods
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for variant in plan.variants:
        for period in plan.periods:
            row = {
                "variant": variant.id,
                "role": variant.role,
                "of": variant.of,
                "change": _changed(variant.settings, base),
                "period": period.name,
                "run_id": runner.record(variant.id, period.name)["run_id"],
                **_run_summary(runner, variant.id, period.name),
            }
            if variant.id != "B0":
                row.update({f"paired_{k}": v for k, v in comparison(variant.id, period).items()})
            rows[(variant.id, period.name)] = row

    family_p = {
        v: rows[(v, dev.name)]["paired_p"]
        for v in plan.holm_family
        if rows[(v, dev.name)]["paired_p"] is not None
    }
    adjusted = holm(family_p)
    verdicts: dict[str, dict[str, Any]] = {}
    b0_dev = rows[("B0", dev.name)]
    for v in plan.holm_family:
        r_dev, r_val = rows[(v, dev.name)], rows[(v, val.name)]
        r_dev["paired_p_holm"] = adjusted.get(v)
        development = development_verdict(
            adjusted.get(v),
            r_dev["paired_mean"],
            r_dev["max_drawdown_pct"],
            b0_dev["max_drawdown_pct"],
            r_dev["paired_tail5_variant"],
            r_dev["paired_tail5_baseline"],
            plan.alpha,
        )
        validation = (
            validation_verdict(r_val["paired_mean"], r_val["paired_ci_conservative"])
            if development == PROMISING
            else None
        )
        verdicts[v] = {
            "development": development,
            "validation": validation,
            "status": final_status(development, validation),
        }
    for v, verdict in verdicts.items():
        if verdict["development"] == PROMISING:
            grid(plan.variant(v))

    # --- the baseline's own edge ----------------------------------------------------------
    edge: dict[str, Any] = {}
    for period in plan.periods:
        own = pair(runner.trades[("B0", period.name)], runner.trades[("B0", period.name)])
        edge[period.name] = describe(
            own.baseline_common, plan.seed, plan.resamples, plan.block_length
        )
    edge["verdict"] = edge_verdict(
        edge[dev.name]["ci_conservative"], edge[val.name]["ci_conservative"]
    )

    # --- sensitivity families, plateau check, cost grid, regimes ---------------------------
    family_rows = []
    for name, setting, members in _families(plan):
        for period in plan.periods:
            means = []
            for m in members:
                r = rows[(m.id, period.name)]
                mean = r.get("paired_mean", 0.0 if m.id == "B0" else math.nan)
                means.append(mean)
                family_rows.append(
                    {
                        "family": name,
                        "setting": setting,
                        "value": m.settings[setting],
                        "variant": m.id,
                        "role": m.role,
                        "period": period.name,
                        "mean_d_pct": mean,
                        "ci_conservative": r.get("paired_ci_conservative"),
                        "net_pnl_rs": r["net_pnl_rs"],
                        "trades": r["trades"],
                        "max_drawdown_pct": r["max_drawdown_pct"],
                    }
                )
            # The entry-timing family is centred on the baseline itself, whose difference from
            # itself is 0 by definition: there is no sign to compare, so no plateau check.
            primary = next((i for i, m in enumerate(members) if m.id == name), None)
            if primary is not None and len(members) > 1 and name != plan.baseline.id:
                neighbours = [means[i] for i in (primary - 1, primary + 1) if 0 <= i < len(members)]
                same = all(
                    not math.isnan(n) and math.copysign(1, n) == math.copysign(1, means[primary])
                    for n in neighbours
                )
                for fr in family_rows[-len(members) :]:
                    fr["plateau_same_sign"] = same

    # Cost grid: the baseline, and every variant the rule marked promising on development.
    grid_bases = {"B0"} | {v for v, x in verdicts.items() if x["development"] == PROMISING}
    cost_rows = []
    for record in runner.records:
        if record["variant"] not in grid_bases:
            continue
        summary = _run_summary(runner, record["key"], record["period"])
        cost_rows.append(
            {
                "base": record["variant"],
                "period": record["period"],
                "slippage_points_per_leg": record["settings"]["slippage_points_per_leg"],
                "brokerage_per_order_rs": record["settings"]["brokerage_per_order_rs"],
                "trades": summary["trades"],
                "net_pnl_rs": summary["net_pnl_rs"],
                "mean_pct_premium_net": summary.get("mean_pct_premium_executed"),
                "t_pct_premium": summary.get("t_pct_premium_executed"),
                "sharpe_notional": summary.get("sharpe_notional"),
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "run_id": record["run_id"],
            }
        )

    regimes = _regimes(plan, runner, data)
    study = strict_json(
        {
            "study_id": study_id,
            "created_at": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            "plan": {
                "name": plan.name,
                "path": str(plan_path),
                "sha256": _sha256(plan_path),
                "preregistration_path": str(preregistration_path),
                "preregistration_sha256": _sha256(preregistration_path),
                "git": git,
                "periods": [
                    {"name": p.name, "start": p.start.isoformat(), "end": p.end.isoformat()}
                    for p in plan.periods
                ],
                "forward_holdout": {
                    "first_entry": plan.forward_first_entry.isoformat(),
                    "min_trades": plan.forward_min_trades,
                    "latest_evaluation": plan.forward_latest_evaluation.isoformat(),
                },
                "holm_family": list(plan.holm_family),
                "alpha": plan.alpha,
                "seed": plan.seed,
                "bootstrap_resamples": plan.resamples,
                "block_length": plan.block_length,
                "thresholds": plan.thresholds,
            },
            "edge": edge,
            "verdicts": verdicts,
            "comparison": list(rows.values()),
            "families": family_rows,
            "cost_grid": cost_rows,
            "regimes": regimes,
            "runs": runner.records,
        }
    )
    _write_outputs(folder, study)
    log(f"study written to {folder}")
    return folder


def _write_outputs(folder: Path, study: dict[str, Any]) -> None:
    from nifty_backtest.research.report import report_markdown

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "study.json").write_text(
        json.dumps(study, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )
    flat = []
    for row in study["comparison"]:
        flat.append(
            {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in row.items()}
        )
    pd.DataFrame(flat).to_csv(folder / "comparison.csv", index=False)
    pd.DataFrame(study["families"]).to_csv(folder / "families.csv", index=False)
    pd.DataFrame(study["cost_grid"]).to_csv(folder / "cost_grid.csv", index=False)
    pd.DataFrame(study["regimes"]).to_csv(folder / "regimes.csv", index=False)
    (folder / "report.md").write_text(report_markdown(study), encoding="utf-8")
