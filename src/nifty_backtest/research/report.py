"""report.md for a study: a readable view of study.json (no new calculation here)."""

import math
from typing import Any


def _num(value: Any, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{100 * value:.2f}%"


def _ci(value: Any) -> str:
    if not value:
        return "n/a"
    return f"[{value[0]:.2f}, {value[1]:.2f}]"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def report_markdown(study: dict[str, Any]) -> str:
    plan = study["plan"]
    dev, val = (p["name"] for p in plan["periods"])
    rows = {(r["variant"], r["period"]): r for r in study["comparison"]}
    out = [
        f"# Study {study['study_id']}",
        "",
        f"- **Plan:** `{plan['path']}` (sha256 `{plan['sha256'][:12]}`), pre-registration "
        f"`{plan['preregistration_path']}` (sha256 `{plan['preregistration_sha256'][:12]}`), "
        f"committed at `{plan['git']['head'][:7]}`.",
        "- **Periods:** "
        + "; ".join(f"{p['name']} {p['start']} to {p['end']}" for p in plan["periods"])
        + ". The validation period was previously observed (M4): it can show inconsistency but "
        "cannot confirm anything.",
        f"- **Forward holdout:** trades entered from {plan['forward_holdout']['first_entry']}, "
        f"evaluated once at {plan['forward_holdout']['min_trades']} completed trades or on "
        f"{plan['forward_holdout']['latest_evaluation']}, whichever comes first.",
        f"- **Statistics:** two-sided paired t-test, Holm across {', '.join(plan['holm_family'])} "
        f"(alpha {plan['alpha']}); 95% percentile bootstrap, {plan['bootstrap_resamples']:,} "
        f"resamples, seed {plan['seed']}, i.i.d. and moving blocks of {plan['block_length']}; "
        "verdicts use the conservative envelope of the two intervals (lower of the lower bounds, "
        "higher of the upper bounds).",
        "- **Unit:** paired differences are in **% of the baseline's premium** for the same "
        "expiry; a skipped week counts as 0 points.",
        "",
        "## Does the baseline have an edge?",
        "",
    ]
    edge = study["edge"]
    out.append(
        _table(
            [
                "Period",
                "Trades",
                "Mean net % of premium",
                "t",
                "95% CI (i.i.d.)",
                "95% CI (blocks)",
                "Lag-1 autocorr.",
            ],
            [
                [
                    name,
                    str(edge[name]["n"]),
                    _num(edge[name]["mean"]),
                    _num(edge[name]["t"]),
                    _ci(edge[name]["ci_iid"]),
                    _ci(edge[name]["ci_block"]),
                    _num(edge[name]["lag1_autocorrelation"], 3),
                ]
                for name in (dev, val)
            ],
        )
    )
    out += ["", f"**Verdict:** {edge['verdict']}.", "", "## Pre-registered variants", ""]
    verdict_rows = []
    for v in plan["holm_family"]:
        d, w = rows[(v, dev)], rows[(v, val)]
        b = rows[("B0", dev)]
        verdict = study["verdicts"][v]
        verdict_rows.append(
            [
                v,
                d["change"],
                _num(d["paired_mean"]),
                _num(d.get("paired_p_holm"), 3),
                _ci(d["paired_ci_conservative"]),
                f"{_pct(d['max_drawdown_pct'])} vs {_pct(b['max_drawdown_pct'])}",
                f"{_num(d['paired_tail5_variant'])} vs {_num(d['paired_tail5_baseline'])}",
                _num(w["paired_mean"]),
                _ci(w["paired_ci_conservative"]),
                verdict["status"],
            ]
        )
    out.append(
        _table(
            [
                "Variant",
                "Change",
                "Dev: mean diff",
                "Dev: Holm p",
                "Dev: CI",
                "Dev: max DD vs B0",
                "Dev: worst-5% vs B0",
                "Validation: mean diff",
                "Validation: CI",
                "Status",
            ],
            verdict_rows,
        )
    )
    out += ["", "## Every run", ""]
    for period in (dev, val):
        out += [f"### {period}", ""]
        table = []
        for r in study["comparison"]:
            if r["period"] != period:
                continue
            table.append(
                [
                    r["variant"],
                    r["role"],
                    r["change"],
                    str(r["trades"]),
                    _num(r.get("net_pnl_rs"), 0),
                    _pct(r.get("roi")),
                    _pct(r.get("max_drawdown_pct")),
                    _num(r.get("sharpe_notional")),
                    _num(r.get("mean_pct_premium_executed")),
                    _num(r.get("paired_mean")),
                    _ci(r.get("paired_ci_conservative")),
                ]
            )
        out.append(
            _table(
                [
                    "Variant",
                    "Role",
                    "Change",
                    "Trades",
                    "Net ₹",
                    "ROI",
                    "Max DD",
                    "Sharpe (notional)",
                    "Mean % premium (executed)",
                    "Mean diff vs B0",
                    "CI",
                ],
                table,
            )
        )
        out.append("")
    out += ["## Sensitivity families (reported in full, never used to choose)", ""]
    out.append(
        _table(
            [
                "Family",
                "Setting",
                "Value",
                "Variant",
                "Period",
                "Mean diff vs B0",
                "CI",
                "Plateau (neighbours same sign)",
            ],
            [
                [
                    f["family"],
                    f["setting"],
                    _num(f["value"], 4) if isinstance(f["value"], float) else str(f["value"]),
                    f["variant"],
                    f["period"],
                    _num(f["mean_d_pct"]),
                    _ci(f["ci_conservative"]),
                    _num(f.get("plateau_same_sign")),
                ]
                for f in study["families"]
            ],
        )
    )
    out += ["", "## Cost grid", ""]
    out.append(
        _table(
            [
                "Base",
                "Period",
                "Slippage (pts/leg)",
                "Brokerage (₹/order)",
                "Trades",
                "Net ₹",
                "Mean % premium",
                "t",
                "Max DD",
            ],
            [
                [
                    c["base"],
                    c["period"],
                    _num(c["slippage_points_per_leg"], 1),
                    _num(c["brokerage_per_order_rs"], 0),
                    str(c["trades"]),
                    _num(c["net_pnl_rs"], 0),
                    _num(c["mean_pct_premium_net"]),
                    _num(c["t_pct_premium"]),
                    _pct(c["max_drawdown_pct"]),
                ]
                for c in sorted(
                    study["cost_grid"],
                    key=lambda c: (
                        c["base"],
                        c["period"],
                        c["slippage_points_per_leg"],
                        c["brokerage_per_order_rs"],
                    ),
                )
            ],
        )
    )
    out += ["", "## Baseline by regime (descriptive)", ""]
    out.append(
        _table(
            ["Period", "Grouping", "Group", "Trades", "Mean net % premium", "Net ₹", "Win rate"],
            [
                [
                    g["period"],
                    g["grouping"],
                    g["group"],
                    str(g["trades"]),
                    _num(g["mean_pct_premium_net"]),
                    _num(g["total_net_rs"], 0),
                    _pct(g["win_rate"]),
                ]
                for g in study["regimes"]
            ],
        )
    )
    return "\n".join(out) + "\n"
