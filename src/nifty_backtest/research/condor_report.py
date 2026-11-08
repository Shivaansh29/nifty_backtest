"""report.md for the M9 iron condor study: a readable view of study.json (no new calculation).

The report keeps verdicts and descriptions apart (plan §9.4): only Q2's pre-registered rule and
Q1's edge rule give verdicts; everything else is labelled "Descriptive only".
"""

from typing import Any

from nifty_backtest.research.report import _ci, _num, _pct, _table

ASSUMPTIONS = [
    "**Stamp duty on cash exercise: Rs 0.** A modelling assumption from statutory "
    "interpretation, not a verified legal fact (plan §6.5). Hypothetical cases A and B are "
    "below; they are not legal limits.",
    "**IPFT in the GST base: included.** An unverified modelling assumption, not a confirmed "
    "statutory requirement; broker practice differs (plan §6.6). The base without IPFT (the "
    "M3-M7 treatment) is a sensitivity below.",
    "**SEBI notional value: settlement level x quantity.** An unverified modelling assumption; "
    "no fee-specific definition was found (plan §6.7). Two alternatives are below.",
    "**Brokerage on exercise: Rs 0** (no order is placed), an assumption.",
    "**No NSE transaction charge or IPFT on exercise:** rests on the absence of such a rule in "
    "the circulars, not on a positive statement.",
]


def condor_report_markdown(study: dict[str, Any]) -> str:
    plan = study["plan"]
    dev, val = (p["name"] for p in plan["periods"])
    rows = {(r["variant"], r["period"]): r for r in study["comparison"]}
    out = [
        f"# Study {study['study_id']}: NIFTY iron condor (M9)",
        "",
        f"- **Plan (frozen):** `{plan['path']}` (sha256 `{plan['sha256'][:12]}`), "
        f"pre-registration `{plan['preregistration_path']}` (sha256 "
        f"`{plan['preregistration_sha256'][:12]}`), committed at `{plan['git']['head'][:7]}`.",
        "- **Periods:** "
        + "; ".join(f"{p['name']} {p['start']} to {p['end']}" for p in plan["periods"])
        + ". Validation was previously observed for the straddle: it can reject a variant but "
        "cannot independently confirm one.",
        f"- **Forward holdout:** entries from {plan['forward_holdout']['first_entry']}, evaluated "
        f"once at {plan['forward_holdout']['min_trades']} completed B0 trades or on "
        f"{plan['forward_holdout']['latest_evaluation']}. Not computed here.",
        f"- **Statistics:** paired two-sided t-test, Holm across {', '.join(plan['holm_family'])} "
        f"(alpha {plan['alpha']}); 95% percentile bootstrap, {plan['bootstrap_resamples']:,} "
        f"resamples, seed {plan['seed']}, i.i.d. and circular blocks of {plan['block_length']}; "
        "verdicts use the conservative envelope of the two intervals.",
        "- **Units:** R_P = net points per unit / P (the ATM straddle premium, not traded), "
        "% (primary). R_ML = net points / maximum loss, % (secondary). Pairs (Q2): d_pct in % "
        "of B0's filled premium for the same expiry; a skipped week counts as 0 points.",
        f"- **GST base:** IPFT {'included' if plan['gst_on_ipft'] else 'excluded'} for every run.",
        "",
        "## Stated assumptions",
        "",
        *[f"- {a}" for a in ASSUMPTIONS],
        "",
        "## Verdicts (pre-registered rule)",
        "",
        "### Q2. Does a condor improve on B0? (M7's rule, unchanged)",
        "",
    ]
    verdict_rows = []
    for v, verdict in study["verdicts"].items():
        r = rows[(v, dev)]
        verdict_rows.append(
            [
                v,
                str(r["paired_n"]),
                _num(r.get("paired_mean")),
                _ci(r.get("paired_ci_conservative")),
                _num(r.get("paired_p_holm"), 4),
                verdict["development"],
                verdict["validation"] or "not checked",
                verdict["status"],
            ]
        )
    out += [
        _table(
            [
                "Variant",
                "Pairs",
                "Mean d_pct (dev)",
                "Envelope",
                "Holm p",
                "Development",
                "Validation",
                "Status",
            ],
            verdict_rows,
        ),
        "",
        'A condor gives up premium, so "worse than baseline" may only mean "collected less": '
        "read Q2 beside Q3. Inconclusive means the data cannot tell, not that there is no effect.",
        "",
        "### Q1. Does it have an edge on its own? (R_P)",
        "",
    ]
    q1_rows = [
        [
            r["variant"],
            r["period"],
            str(r["n"]),
            _num(r["mean"]),
            _ci(r["ci_conservative"]),
            _num(r.get("mean_r_ml")),
            _num(r.get("mean_pct_net_credit")),
            r["verdict"],
        ]
        for r in study["q1"]
    ]
    out += [
        _table(
            [
                "Variant",
                "Period",
                "Trades",
                "Mean R_P %",
                "Envelope",
                "Mean R_ML % (descr.)",
                "% of net credit (descr.)",
                "Verdict",
            ],
            q1_rows,
        ),
        "",
        "## Descriptive only (no verdict, never used to choose a setting)",
        "",
        "### Q3. Risk trade-off",
        "",
    ]
    q3_rows = [
        [
            r["variant"],
            r["period"],
            str(r["trades"]),
            _num(r["net_pnl_rs"]),
            _pct(r["max_drawdown_pct"]),
            _num(r["lot_free_max_drawdown"], 4),
            _num(r.get("net_over_max_drawdown")),
            _num(r.get("worst_trade_rs")),
            _num(r.get("tail5_common")),
            _pct(r.get("win_rate")),
            _num(r.get("max_loss_hits"), 0),
        ]
        for r in study["q3"]
    ]
    out += [
        _table(
            [
                "Variant",
                "Period",
                "Trades",
                "Net Rs",
                "Max DD %",
                "Lot-free DD",
                "Net / max DD",
                "Worst Rs",
                "Worst 5% (B0 premium %)",
                "Win rate",
                "Max-loss hits",
            ],
            q3_rows,
        ),
        "",
        "Rupee totals use each trade's own lot size (25 to 75), so they weigh years unequally; "
        "the lot-free drawdown (cumulative notional return) does not.",
        "",
        "### C1-R realism check (strikes from the previous session)",
        "",
    ]
    for p in (dev, val):
        r = rows.get(("C1-R", p))
        if r:
            out.append(
                f"- {p}: mean d_pct against C1 (in B0's premium) {_num(r.get('paired_mean'))}, "
                f"envelope {_ci(r.get('paired_ci_conservative'))}, {r['trades']} trades."
            )
    out += ["", "### Cost grid", ""]
    out.append(
        _table(
            ["Base", "Period", "Slippage", "Brokerage", "Trades", "Net Rs", "Mean R_P %"],
            [
                [
                    c["base"],
                    c["period"],
                    _num(c["slippage_points_per_leg"], 1),
                    _num(c["brokerage_per_order_rs"], 0),
                    str(c["trades"]),
                    _num(c["net_pnl_rs"]),
                    _num(c.get("mean_r_p")),
                ]
                for c in study["cost_grid"]
            ],
        )
    )
    out += [
        "",
        "### Cost-assumption sensitivities",
        "",
        "Hypothetical cases, not estimates and not legal limits. Verdicts above are computed on "
        'the stated assumptions; "status would be" only says what the rule would give.',
        "",
        _table(
            [
                "Sensitivity",
                "Case",
                "Variant",
                "Period",
                "Extra cost Rs",
                "Mean R_P %",
                "Mean d_pct",
                "Holm p",
                "Status would be",
                "Changes?",
            ],
            [
                [
                    s["sensitivity"],
                    s["case"],
                    s["variant"],
                    s["period"],
                    _num(s["extra_cost_rs"], 4),
                    _num(s.get("mean_r_p")),
                    _num(s.get("paired_mean")),
                    _num(s.get("p_holm"), 4),
                    s.get("status_would_be", ""),
                    _num(s.get("verdict_changes")) if "verdict_changes" in s else "",
                ]
                for s in study["sensitivities"]
            ],
        ),
        "",
        "### Trade traces (picked by code, checked by hand against raw NSE files)",
        "",
        f"- {study['trace']['variant']}, {study['trace']['period']}: first expiry with a bought "
        f"leg in the money `{study['trace']['bought_leg_in_the_money']}`; first with none "
        f"`{study['trace']['no_bought_leg_in_the_money']}`.",
        "",
    ]
    return "\n".join(out)
