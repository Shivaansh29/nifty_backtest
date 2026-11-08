"""Run the pre-registered M9 iron condor study (docs/research/m9_iron_condor_plan.md, §7).

    nifty-backtest study docs/research/m9_plan.toml

1. The plan must be frozen and, with its pre-registration, committed and unchanged; the study
   records both SHA-256 hashes and the commit. Results can only come after the plan.
2. Every variant (B0, C1, C2, C3, C1-R) runs in both periods as a normal saved run, with the
   plan's GST base for every run. Then the cost grid for B0 and C1 (and any primary the rule
   marks promising on development).
3. Q1 (edge on its own): mean R_P per period with both bootstrap intervals and their envelope.
   Q2 (improves on B0): M7's paired rule, unchanged, on d_pct in % of B0's filled premium,
   Holm across C1-C3. Q3 (risk trade-off): reported, no verdict.
4. Descriptive only, never a verdict: C1-R against C1 (in B0's premium), the cost grid, and the
   stamp-duty, SEBI-notional and GST-base sensitivities, recomputed from the saved files.
5. Writes study.json, comparison.csv, q1.csv, q3.csv, cost_grid.csv, sensitivities.csv and
   report.md. The validation period ends where the plan says, so newer data is never read.
"""

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from nifty_backtest.costs.model import CostConfig, RateTable
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.metrics.series import load_run, notional_returns
from nifty_backtest.metrics.stats import max_drawdown
from nifty_backtest.metrics.summary import strict_json
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
from nifty_backtest.research.condor_plan import CondorPlan, load_condor_plan, run_config
from nifty_backtest.research.plan import Period, PlanError, Variant
from nifty_backtest.research.stats import holm, worst_share_mean
from nifty_backtest.research.study import Runner, StudyError, _run_summary, plan_git_state

__all__ = ["StudyError", "run_condor_study"]

R_P = "pnl_pct_reference_premium_net"
R_ML = "pnl_pct_max_loss_net"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dates(values: pd.Series) -> list[date]:
    return [date.fromisoformat(str(v)[:10]) for v in values]


def r_p(trades: pd.DataFrame) -> list[float]:
    """R_P per trade: 100 x net points per unit / P. A condor saves it; for the straddle
    (B0), P is its own ATM premium at the close, the same P the condor uses that week."""
    if trades.empty:
        return []
    if R_P in trades:
        return [float(x) for x in trades[R_P]]
    return [
        100 * float(n) / float(p)
        for n, p in zip(trades["pnl_points_net"], trades["premium_close_points"], strict=True)
    ]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _max_loss_hits(trades: pd.DataFrame) -> int | None:
    """Trades that lost the whole widest wing before costs (settled beyond that long strike)."""
    if trades.empty or "wing_call_points" not in trades:
        return None
    widest = trades[["wing_call_points", "wing_put_points"]].max(axis=1)
    return int((trades["value_at_expiry_points"] >= widest - 1e-9).sum())


def lot_free_drawdown(folder: Path) -> tuple[float, bool]:
    """Largest peak-to-trough fall of the cumulative sum of daily notional_net returns (plan §8):
    a drawdown in return-on-notional units that does not depend on the lot size. Missing days
    are skipped and flagged, never filled: with gaps it is an observed lower bound. A run with
    no trades has no position, so no drawdown."""
    if (folder / "trades.csv").read_text(encoding="utf-8").strip() == "":
        return 0.0, False
    returns = notional_returns(load_run(folder), net=True)
    gaps = bool(returns.isna().any())
    peak, worst, level = 0.0, 0.0, 0.0
    for value in returns.dropna().tolist():
        level += float(value)
        peak = max(peak, level)
        worst = max(worst, peak - level)
    return worst, gaps


class Rates:
    """The dated rates the sensitivities need, from the same table the engine used."""

    def __init__(self, path: Path) -> None:
        self.table = RateTable(path)

    def stamp(self, on: date) -> float:
        return self.table.rate("stamp_duty", "option_purchase", on)

    def sebi_notional(self, on: date) -> float:
        return self.table.rate("sebi_fee", "option_assignment", on)

    def gst(self, on: date) -> float:
        return self.table.rate("gst", "services", on)


def _in_the_money_legs(
    trades: pd.DataFrame, legs: pd.DataFrame | None, slippage: float
) -> list[dict[str, Any]]:
    """Every leg that expired in the money: (trade_id, expiry, side, strike, entry fill,
    settlement, quantity). Condors from legs.csv; the straddle from its trade row (one leg can
    be in the money), its fill rebuilt as the engine fills a sale: close - slippage, floor 0."""
    out: list[dict[str, Any]] = []
    if trades.empty:
        return out
    info = trades.set_index("trade_id")
    if legs is not None:
        for leg in legs.to_dict("records"):
            if leg["expiry_status"] == "worthless":
                continue
            trade = info.loc[leg["trade_id"]]
            out.append(
                {
                    "trade_id": str(leg["trade_id"]),
                    "expiry": date.fromisoformat(str(trade["expiry"])[:10]),
                    "side": leg["side"],
                    "status": leg["expiry_status"],
                    "strike": float(leg["strike"]),
                    "entry_fill": float(leg["entry_fill"]),
                    "intrinsic": float(leg["intrinsic_at_expiry"]),
                    "settlement": float(trade["settlement_level"]),
                    "quantity": int(leg["quantity"]),
                }
            )
        return out
    for trade_id, trade in info.iterrows():
        for kind in ("ce", "pe"):
            value = float(trade[f"{kind}_value_at_expiry"])
            if value > 0:
                out.append(
                    {
                        "trade_id": trade_id,
                        "expiry": date.fromisoformat(str(trade["expiry"])[:10]),
                        "side": "sell",
                        "status": "assigned",
                        "strike": float(trade["strike"]),
                        "entry_fill": max(float(trade[f"{kind}_entry_close"]) - slippage, 0.0),
                        "intrinsic": value,
                        "settlement": float(trade["settlement_level"]),
                        "quantity": int(trade["quantity"]),
                    }
                )
    return out


def extra_costs(
    case: str,
    trades: pd.DataFrame,
    legs: pd.DataFrame | None,
    slippage: float,
    rates: Rates,
    gst_on_ipft: bool,
) -> dict[str, float]:
    """Rupee cost each trade would ADD under one sensitivity case (negative: a saving).

    Stamp duty on cash exercise (plan §6.5; the plan charges 0), on exercised BOUGHT legs only:
      intrinsic_value_x_quantity   stamp rate x intrinsic value x quantity
      settlement_level_x_quantity  stamp rate x settlement level x quantity (stress)
    SEBI notional (plan §6.7; the plan uses settlement x quantity), on every in-the-money leg:
      strike_x_quantity, strike_plus_entry_fill_x_quantity
                                   SEBI rate x (alternative - settlement x quantity) x (1 + GST)
    GST base (plan §6.6; the plan includes IPFT):
      ipft_excluded_from_gst_base  -GST rate x IPFT, the M3-M7 treatment
    """
    out = {str(t): 0.0 for t in trades["trade_id"]} if not trades.empty else {}
    if case == "ipft_excluded_from_gst_base":
        if gst_on_ipft:
            for trade_id, entry, ipft in zip(
                trades["trade_id"], _dates(trades["entry_date"]), trades["ipft_rs"], strict=True
            ):
                out[str(trade_id)] = -rates.gst(entry) * float(ipft)
        return out
    for leg in _in_the_money_legs(trades, legs, slippage):
        q, expiry = leg["quantity"], leg["expiry"]
        if case in ("intrinsic_value_x_quantity", "settlement_level_x_quantity"):
            if leg["side"] != "buy":
                continue
            base = leg["intrinsic"] if case == "intrinsic_value_x_quantity" else leg["settlement"]
            out[leg["trade_id"]] += rates.stamp(expiry) * base * q
        elif case in ("strike_x_quantity", "strike_plus_entry_fill_x_quantity"):
            alternative = leg["strike"] + (
                leg["entry_fill"] if case == "strike_plus_entry_fill_x_quantity" else 0.0
            )
            change = (alternative - leg["settlement"]) * q
            out[leg["trade_id"]] += rates.sebi_notional(expiry) * change * (1 + rates.gst(expiry))
        else:
            raise ValueError(f"unknown sensitivity case {case!r}")
    return out


def adjusted(trades: pd.DataFrame, extra: dict[str, float]) -> pd.DataFrame:
    """The trade log as it would be with these extra costs (descriptive only)."""
    if trades.empty:
        return trades
    out = trades.copy()
    delta = out["trade_id"].map(extra).fillna(0.0)
    out["pnl_rs_net"] = out["pnl_rs_net"] - delta
    out["pnl_points_net"] = out["pnl_rs_net"] / out["quantity"]
    if R_P in out:
        out[R_P] = 100 * out["pnl_points_net"] / out["reference_premium_points"]
    return out


def adjusted_drawdown_pct(folder: Path, trades: pd.DataFrame, extra: dict[str, float]) -> float:
    """Max drawdown % of the equity curve with the extra costs booked on each expiry day. A run
    with no trades is flat (0), as its comparison row says."""
    if trades.empty:
        return 0.0
    run = load_run(folder)
    equity = pd.Series(run.equity["equity_rs"].to_numpy(dtype=float), index=run.days)
    if not trades.empty:
        booked = pd.Series(0.0, index=run.days)
        for trade_id, expiry in zip(trades["trade_id"], _dates(trades["expiry"]), strict=True):
            booked.loc[booked.index >= expiry] += extra.get(str(trade_id), 0.0)
        equity = equity - booked
    return max_drawdown(equity, run.capital).max_pct


def run_condor_study(
    plan_path: Path,
    preregistration_path: Path,
    data: DataConfig,
    costs: CostConfig,
    studies_dir: Path = Path("studies"),
    require_committed: bool = True,
    log: Callable[[str], None] = print,
) -> Path:
    try:
        plan = load_condor_plan(plan_path)
    except PlanError as exc:
        raise StudyError(str(exc)) from exc
    git = plan_git_state([plan_path, preregistration_path])
    if require_committed and not git["head"]:
        raise StudyError(
            "git is not available here (or this is not a git checkout), so the plan cannot be "
            "shown to be committed: run studies from a git checkout, not inside the Docker image"
        )
    if require_committed and (
        git["uncommitted_changes"] or not all(f["last_commit"] for f in git["files"].values())
    ):
        raise StudyError(
            "the study plan and pre-registration must be committed, unchanged, before any "
            "variant runs"
        )
    study_id = f"{datetime.now():%Y%m%d-%H%M%S}-{plan.name}"
    folder = studies_dir / study_id

    def configure(settings: dict[str, Any], period: Period, d: DataConfig, c: CostConfig) -> Any:
        return run_config(plan, settings, period, d, c)

    runner = Runner(folder / "runs", data, costs, log, configure=configure)
    for variant in plan.variants:
        for period in plan.periods:
            runner.run(variant.id, variant.settings, period, variant)

    grid_keys: dict[str, list[str]] = {}

    def grid(variant: Variant) -> None:
        keys = grid_keys.setdefault(variant.id, [variant.id])
        for slip in plan.grid_slippage:
            for brokerage in plan.grid_brokerage:
                settings = variant.settings | {
                    "slippage_points_per_leg": slip,
                    "brokerage_per_order_rs": brokerage,
                }
                if settings == variant.settings:
                    continue  # the variant itself is the grid's own cell
                key = f"{variant.id}@slip{slip:g}-brk{brokerage:g}"
                keys.append(key)
                for period in plan.periods:
                    runner.run(key, settings, period, variant)

    for target in plan.grid_targets:  # unconditional (plan §7)
        grid(plan.variant(target))

    dev, val = plan.periods
    trades = runner.trades
    rates = Rates(costs.rates_path)
    run_folder = {(r["key"], r["period"]): folder / "runs" / r["run_id"] for r in runner.records}

    # --- Q1: does the condor have an edge on its own? (R_P) ----------------------------------
    q1_ids = ["B0", *plan.holm_family]
    q1: list[dict[str, Any]] = []
    for vid in q1_ids:
        stats = {
            p.name: describe(
                r_p(trades[(vid, p.name)]), plan.seed, plan.resamples, plan.block_length
            )
            for p in plan.periods
        }
        verdict = edge_verdict(
            stats[dev.name]["ci_conservative"], stats[val.name]["ci_conservative"]
        )
        for p in plan.periods:
            t = trades[(vid, p.name)]
            q1.append(
                {
                    "variant": vid,
                    "period": p.name,
                    **stats[p.name],
                    "mean_r_ml": float(t[R_ML].mean()) if R_ML in t and not t.empty else None,
                    "mean_pct_net_credit": float(t["pnl_pct_premium_net"].mean())
                    if R_P in t and not t.empty
                    else None,
                    "verdict": verdict,
                }
            )
    # B0's own Q1 row, in the layout M7's study.json uses for "edge" (same statistics, on R_P).
    not_stats = ("variant", "period", "verdict", "mean_r_ml", "mean_pct_net_credit")
    edge_block: dict[str, Any] = {
        row["period"]: {k: v for k, v in row.items() if k not in not_stats}
        for row in q1
        if row["variant"] == "B0"
    }
    edge_block["verdict"] = next(r["verdict"] for r in q1 if r["variant"] == "B0")

    # --- Q2: comparison with B0 (M7's rule), and every variant's own numbers -----------------
    def paired(vid: str, period: str) -> tuple[dict[str, Any], str]:
        variant = plan.variant(vid)
        if variant.role == "realism" and variant.of:
            pairing = pair(
                trades[(variant.of, period)], trades[(vid, period)], trades[("B0", period)]
            )
            return compare(pairing, plan.seed, plan.resamples, plan.block_length), variant.of
        pairing = pair(trades[("B0", period)], trades[(vid, period)])
        return compare(pairing, plan.seed, plan.resamples, plan.block_length), "B0"

    rows: dict[tuple[str, str], dict[str, Any]] = {}
    base = plan.baseline.settings
    for variant in plan.variants:
        for p in plan.periods:
            t = trades[(variant.id, p.name)]
            row: dict[str, Any] = {
                "variant": variant.id,
                "role": variant.role,
                "of": variant.of,
                "change": ", ".join(
                    f"{k}={variant.settings[k]}"
                    for k in variant.settings
                    if variant.settings[k] != base[k]
                )
                or "baseline",
                "period": p.name,
                "run_id": runner.record(variant.id, p.name)["run_id"],
                **_run_summary(runner, variant.id, p.name),
                "mean_r_p": _mean(r_p(t)),
                "mean_r_ml": float(t[R_ML].mean()) if R_ML in t and not t.empty else None,
                "max_loss_hits": _max_loss_hits(t),
            }
            if variant.id != "B0":
                stats, against = paired(variant.id, p.name)
                row.update({f"paired_{k}": v for k, v in stats.items()})
                row["paired_against"] = against
                row["paired_denominator"] = "B0 filled premium"
            rows[(variant.id, p.name)] = row

    def verdicts_for(
        means: dict[str, dict[str, float]],
        pvalues: dict[str, float],
        drawdowns: dict[str, float],
        tails: dict[str, tuple[float | None, float | None]],
        val_stats: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        adjusted_p = holm({v: p for v, p in pvalues.items() if p is not None})
        out = {}
        for v in plan.holm_family:
            development = development_verdict(
                adjusted_p.get(v),
                means[v][dev.name],
                drawdowns[v],
                drawdowns["B0"],
                tails[v][0],
                tails[v][1],
                plan.alpha,
            )
            validation = (
                validation_verdict(val_stats[v]["mean"], val_stats[v]["ci_conservative"])
                if development == PROMISING
                else None
            )
            out[v] = {
                "development": development,
                "validation": validation,
                "status": final_status(development, validation),
                "p_holm": adjusted_p.get(v),
            }
        return out

    actual = verdicts_for(
        {
            v: {p.name: rows[(v, p.name)]["paired_mean"] for p in plan.periods}
            for v in plan.holm_family
        },
        {v: rows[(v, dev.name)]["paired_p"] for v in plan.holm_family},
        {v: rows[(v, dev.name)]["max_drawdown_pct"] for v in ["B0", *plan.holm_family]},
        {
            v: (
                rows[(v, dev.name)]["paired_tail5_variant"],
                rows[(v, dev.name)]["paired_tail5_baseline"],
            )
            for v in plan.holm_family
        },
        {
            v: {
                "mean": rows[(v, val.name)]["paired_mean"],
                "ci_conservative": rows[(v, val.name)]["paired_ci_conservative"],
            }
            for v in plan.holm_family
        },
    )
    verdicts = {v: {k: x for k, x in got.items() if k != "p_holm"} for v, got in actual.items()}
    for v, got in actual.items():
        rows[(v, dev.name)]["paired_p_holm"] = got["p_holm"]
    if plan.grid_add_promising:
        for v, judged in verdicts.items():
            if judged["development"] == PROMISING and v not in grid_keys:
                grid(plan.variant(v))

    # --- Q3: risk trade-off, reported with no verdict -----------------------------------------
    q3: list[dict[str, Any]] = []
    for variant in plan.variants:
        for p in plan.periods:
            r, t = rows[(variant.id, p.name)], trades[(variant.id, p.name)]
            lot_free, gaps = lot_free_drawdown(run_folder[(variant.id, p.name)])
            common = pair(trades[("B0", p.name)], t).variant_common
            values = r_p(t)
            q3.append(
                {
                    "variant": variant.id,
                    "period": p.name,
                    "trades": r["trades"],
                    "net_pnl_rs": r["net_pnl_rs"],
                    "gross_pnl_rs": r.get("gross_pnl_rs"),
                    "max_drawdown_rs": r.get("max_drawdown_rs"),
                    "max_drawdown_pct": r["max_drawdown_pct"],
                    "lot_free_max_drawdown": lot_free,
                    "lot_free_drawdown_lower_bound": gaps,
                    "net_over_max_drawdown": r["net_pnl_rs"] / r["max_drawdown_rs"]
                    if r.get("max_drawdown_rs")
                    else None,
                    "worst_trade_rs": r.get("worst_trade_rs"),
                    "worst_r_p": min(values) if values else None,
                    "tail5_common": worst_share_mean(common),
                    "win_rate": r.get("win_rate"),
                    "max_loss_hits": r["max_loss_hits"],
                }
            )

    # --- cost grid ----------------------------------------------------------------------------
    cost_rows = []
    for target, keys in grid_keys.items():
        for key in keys:
            for p in plan.periods:
                record = runner.record(key, p.name)
                summary = _run_summary(runner, key, p.name)
                cost_rows.append(
                    {
                        "base": target,
                        "period": p.name,
                        "slippage_points_per_leg": record["settings"]["slippage_points_per_leg"],
                        "brokerage_per_order_rs": record["settings"]["brokerage_per_order_rs"],
                        "trades": summary["trades"],
                        "net_pnl_rs": summary["net_pnl_rs"],
                        "mean_pct_premium_net": summary.get("mean_pct_premium_executed"),
                        "t_pct_premium": summary.get("t_pct_premium_executed"),
                        "sharpe_notional": summary.get("sharpe_notional"),
                        "max_drawdown_pct": summary["max_drawdown_pct"],
                        "mean_r_p": _mean(r_p(trades[(key, p.name)])),
                        "run_id": record["run_id"],
                    }
                )

    # --- sensitivities: descriptive, recomputed from the saved files --------------------------
    sensitivities: list[dict[str, Any]] = []
    for name, cases, targets in (
        ("stamp", plan.stamp_cases, plan.stamp_targets),
        ("notional", plan.notional_cases, plan.notional_targets),
        ("gst", plan.gst_cases, plan.gst_targets),
    ):
        for case in cases:
            alt: dict[tuple[str, str], pd.DataFrame] = {}
            extra: dict[tuple[str, str], dict[str, float]] = {}
            for vid in ["B0", *plan.holm_family]:
                for p in plan.periods:
                    period_trades = trades[(vid, p.name)]
                    slip = float(plan.variant(vid).settings["slippage_points_per_leg"])
                    e = (
                        extra_costs(
                            case,
                            period_trades,
                            runner.legs[(vid, p.name)],
                            slip,
                            rates,
                            plan.gst_on_ipft,
                        )
                        if vid in targets
                        else {}
                    )
                    extra[(vid, p.name)] = e
                    alt[(vid, p.name)] = adjusted(period_trades, e)
            case_stats = {
                (vid, p.name): compare(
                    pair(alt[("B0", p.name)], alt[(vid, p.name)]),
                    plan.seed,
                    plan.resamples,
                    plan.block_length,
                )
                for vid in plan.holm_family
                for p in plan.periods
            }
            drawdowns = {
                vid: adjusted_drawdown_pct(
                    run_folder[(vid, dev.name)], trades[(vid, dev.name)], extra[(vid, dev.name)]
                )
                for vid in ["B0", *plan.holm_family]
            }
            would = verdicts_for(
                {
                    v: {p.name: case_stats[(v, p.name)]["mean"] for p in plan.periods}
                    for v in plan.holm_family
                },
                {v: case_stats[(v, dev.name)]["p"] for v in plan.holm_family},
                drawdowns,
                {
                    v: (
                        case_stats[(v, dev.name)]["tail5_variant"],
                        case_stats[(v, dev.name)]["tail5_baseline"],
                    )
                    for v in plan.holm_family
                },
                {
                    v: {
                        "mean": case_stats[(v, val.name)]["mean"],
                        "ci_conservative": case_stats[(v, val.name)]["ci_conservative"],
                    }
                    for v in plan.holm_family
                },
            )
            for vid in targets:
                for p in plan.periods:
                    srow: dict[str, Any] = {
                        "sensitivity": name,
                        "case": case,
                        "variant": vid,
                        "period": p.name,
                        "extra_cost_rs": sum(extra[(vid, p.name)].values()),
                        "mean_r_p": _mean(r_p(alt[(vid, p.name)])),
                    }
                    if vid in plan.holm_family:
                        s = case_stats[(vid, p.name)]
                        srow["paired_mean"] = s["mean"]
                        if p.name == dev.name:
                            srow["p_holm"] = would[vid]["p_holm"]
                            srow["status_would_be"] = would[vid]["status"]
                            srow["verdict_changes"] = (
                                would[vid]["status"] != verdicts[vid]["status"]
                            )
                    sensitivities.append(srow)

    # --- trade traces, picked by code (plan §10; run by hand after this study) ---------------
    trace: dict[str, Any] = {"variant": plan.trace.get("variant", "C1"), "period": dev.name}
    legs = runner.legs.get((trace["variant"], dev.name))
    picked: dict[str, str | None] = {
        "bought_leg_in_the_money": None,
        "no_bought_leg_in_the_money": None,
    }
    traced = trades[(trace["variant"], dev.name)]
    if legs is not None and not traced.empty:
        for trade_id, _expiry in sorted(
            zip(traced["trade_id"], _dates(traced["expiry"]), strict=True), key=lambda x: x[1]
        ):
            mine = legs[legs["trade_id"] == trade_id]
            bought_itm = bool(
                ((mine["side"] == "buy") & (mine["expiry_status"] != "worthless")).any()
            )
            slot = "bought_leg_in_the_money" if bought_itm else "no_bought_leg_in_the_money"
            if picked[slot] is None:
                picked[slot] = str(trade_id)
    trace |= picked

    study = strict_json(
        {
            "study_id": study_id,
            "created_at": f"{datetime.now():%Y-%m-%dT%H:%M:%S}",
            "plan": _plan_info(plan, plan_path, preregistration_path, git),
            "edge": edge_block,
            "verdicts": verdicts,
            "q1": q1,
            "comparison": list(rows.values()),
            "q3": q3,
            "families": [],
            "cost_grid": cost_rows,
            "sensitivities": sensitivities,
            "regimes": [],
            "trace": trace,
            "runs": runner.records,
        }
    )
    _write_outputs(folder, study)
    log(f"study written to {folder}")
    return folder


def _plan_info(
    plan: CondorPlan, plan_path: Path, prereg: Path, git: dict[str, Any]
) -> dict[str, Any]:
    assumptions = plan.raw.get("costs", {}).get("assumptions", {})
    return {
        "schema_version": 2,
        "name": plan.name,
        "path": str(plan_path),
        "sha256": _sha256(plan_path),
        "preregistration_path": str(prereg),
        "preregistration_sha256": _sha256(prereg),
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
        "thresholds": {},
        "structures": [
            {"id": s.id, "strategy": s.strategy, **s.parameters} for s in plan.structures.values()
        ],
        "gst_on_ipft": plan.gst_on_ipft,
        "assumptions": {
            name: {k: v for k, v in block.items() if isinstance(v, (str, bool, int, float))}
            for name, block in assumptions.items()
        },
    }


def _write_outputs(folder: Path, study: dict[str, Any]) -> None:
    from nifty_backtest.research.condor_report import condor_report_markdown

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "study.json").write_text(
        json.dumps(study, indent=2, default=str, allow_nan=False), encoding="utf-8"
    )

    def flat(rows: list[dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()}
                for r in rows
            ]
        )

    for name in ("comparison", "q1", "q3", "cost_grid", "sensitivities"):
        flat(study[name]).to_csv(folder / f"{name}.csv", index=False)
    (folder / "report.md").write_text(condor_report_markdown(study), encoding="utf-8")
