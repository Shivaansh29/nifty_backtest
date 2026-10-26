"""M7 study plan, pairing, verdicts and an end-to-end study on the synthetic test week."""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.research.analysis import (
    CONSISTENT,
    INCONCLUSIVE,
    INCONSISTENT,
    PROMISING,
    WORSE,
    WORSE_TAIL,
    development_verdict,
    edge_verdict,
    envelope,
    final_status,
    pair,
    validation_verdict,
)
from nifty_backtest.research.plan import PlanError, load_plan, run_config
from nifty_backtest.research.study import StudyError, run_study
from tests.helpers import write_index
from tests.test_engine import MON, THU, TUE, WED, setup
from tests.test_engine_conditions import FRI, week_with_friday

REPO = Path(__file__).resolve().parents[1]
PLAN = REPO / "docs" / "research" / "m7_plan.toml"
PREREGISTRATION = REPO / "docs" / "research" / "m7_preregistration.md"


# --- the committed plan ------------------------------------------------------------------


def test_the_m7_plan_obeys_the_preregistration_rules() -> None:
    plan = load_plan(PLAN)  # load_plan itself enforces one change per variant
    assert plan.holm_family == ("V1a", "V1b", "V2", "V3", "V4", "V5")
    assert [(p.start, p.end) for p in plan.periods] == [
        (date(2021, 10, 1), date(2024, 9, 30)),
        (date(2024, 10, 1), date(2026, 10, 16)),
    ]
    assert plan.forward_first_entry == date(2026, 10, 17)
    assert (plan.seed, plan.resamples, plan.block_length) == (20261026, 10_000, 4)
    assert plan.variant("V1a").settings["vix_min"] == plan.thresholds["vix_p33"] == 13.3683
    assert plan.variant("V1b").settings["vix_max"] == plan.thresholds["vix_p67"] == 16.8808
    assert plan.baseline.settings["slippage_points_per_leg"] == 0.5
    assert len(plan.variants) == 25


def test_run_config_switches_on_exactly_the_planned_condition() -> None:
    plan = load_plan(PLAN)
    dev = plan.periods[0]
    data = DataConfig()

    def config(variant_id: str):  # type: ignore[no-untyped-def]
        from nifty_backtest.costs.model import CostConfig

        return run_config(plan.variant(variant_id).settings, dev, data, CostConfig())

    b0, _ = config("B0")
    assert (b0.entry_filter, b0.exit_rule, b0.strike_reference) == (None, None, "entry_close")
    assert (b0.data.start, b0.data.end) == (dev.start, dev.end)
    v3, _ = config("V3")
    assert v3.exit_rule is not None
    assert v3.exit_rule.stop_multiple == 2.0
    v2, _ = config("V2")
    assert v2.entry_filter is not None
    assert v2.entry_filter.skip_scheduled_events
    assert config("B0-R")[0].strike_reference == "previous_close"
    _, e5 = config("E5")
    assert e5.entry_days_before_expiry == 5


def _plan_text(**overrides: str) -> str:
    text = PLAN.read_text()
    for old, new in overrides.items():
        assert old in text
        text = text.replace(old, new, 1)
    return text


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            'id = "V3"\nrole = "primary"\nstop_multiple = 2.0',
            'id = "V3"\nrole = "primary"\nstop_multiple = 2.0\nvix_min = 13.0',
            "exactly one change",
        ),
        (
            'holm_family = ["V1a", "V1b", "V2", "V3", "V4", "V5"]',
            'holm_family = ["V1a", "V2", "V3", "V4", "V5"]',
            "Holm family",
        ),
        ('end = "2026-10-16"', 'end = "2026-10-20"', "before the forward holdout"),
        (
            'id = "V4"\nrole = "primary"\ntake_profit_decay = 0.5',
            'id = "V4"\nrole = "primary"\ntake_profit = 0.5',
            "unknown settings",
        ),
    ],
)
def test_plans_that_break_the_rules_are_refused(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "plan.toml"
    path.write_text(_plan_text(**{old: new}))
    with pytest.raises(PlanError, match=message):
        load_plan(path)


# --- pairing and verdicts ------------------------------------------------------------------

E1, E2, E3, E4 = (date(2025, 1, d) for d in (2, 9, 16, 23))


def test_pairing_uses_the_baseline_premium_for_both_sides() -> None:
    baseline = pd.DataFrame(
        {
            "expiry": [E1.isoformat(), E2.isoformat(), E3.isoformat()],
            "pnl_points_net": [10.0, -20.0, 5.0],
            "premium_fill_points": [100.0, 200.0, 50.0],
        }
    )
    # The variant skipped E1, lost less on E2, matched E3, and traded E4 (not in the baseline).
    variant = pd.DataFrame(
        {
            "expiry": [E2.isoformat(), E3.isoformat(), E4.isoformat()],
            "pnl_points_net": [-5.0, 5.0, 3.0],
            "premium_fill_points": [190.0, 50.0, 80.0],
        }
    )
    p = pair(baseline, variant)
    # E1: 0 - 10 = -10 pts = -10% of 100;  E2: -5 - (-20) = +15 pts = +7.5% of 200;  E3: 0.
    assert p.d_pts == [-10.0, 15.0, 0.0]
    assert p.d_pct == [-10.0, 7.5, 0.0]
    assert p.variant_common == [0.0, -2.5, 10.0]  # the skipped week is 0, not undefined
    assert p.baseline_common == [10.0, -10.0, 10.0]
    assert (p.executed, p.extra_variant_trades) == (2, 1)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ((0.01, 2.0, 0.10, 0.12, -40.0, -45.0), PROMISING),
        ((0.01, -2.0, 0.10, 0.12, -40.0, -45.0), WORSE),
        ((0.01, 2.0, 0.15, 0.12, -40.0, -45.0), WORSE_TAIL),  # deeper drawdown
        ((0.01, 2.0, 0.10, 0.12, -50.0, -45.0), WORSE_TAIL),  # worse tail
        ((0.20, 5.0, 0.10, 0.12, -40.0, -45.0), INCONCLUSIVE),  # not significant after Holm
        ((None, 5.0, 0.10, 0.12, -40.0, -45.0), INCONCLUSIVE),
    ],
)
def test_development_verdicts(
    args: tuple[float | None, float, float, float, float, float], expected: str
) -> None:
    # (Holm p, mean diff, variant max DD, baseline max DD, variant worst-5%, baseline worst-5%)
    p, mean, dd_variant, dd_base, tail_variant, tail_base = args
    verdict = development_verdict(p, mean, dd_variant, dd_base, tail_variant, tail_base, 0.05)
    assert verdict == expected


def test_envelope_is_min_lower_and_max_upper_not_the_wider_interval() -> None:
    # Neither contains the other: (0.1, 2.0) is wider, but (-0.3, 1.0) reaches lower.
    # The envelope keeps the lowest lower bound and the highest upper bound.
    assert envelope((0.1, 2.0), (-0.3, 1.0)) == (-0.3, 2.0)
    assert envelope((1.0, 2.0), (0.5, 3.0)) == (0.5, 3.0)  # nested: the outer one
    assert envelope((1.0, 2.0), None) is None
    # So a variant whose i.i.d. interval clears zero but whose block interval does not
    # is NOT consistent.
    assert validation_verdict(1.0, envelope((0.1, 2.0), (-0.3, 1.0))) == INCONSISTENT


def test_validation_and_final_status() -> None:
    assert validation_verdict(1.0, (0.2, 2.0)) == CONSISTENT
    assert validation_verdict(1.0, (-0.2, 2.0)) == INCONSISTENT  # interval reaches zero
    assert validation_verdict(1.0, None) == INCONSISTENT
    assert final_status(PROMISING, CONSISTENT).startswith("awaiting forward holdout")
    assert final_status(PROMISING, INCONSISTENT).startswith("not supported")
    assert final_status(INCONCLUSIVE, None) == "inconclusive"
    # Nothing is ever "confirmed" from previously observed data.
    assert all(
        "confirmed" not in final_status(d, v)
        for d in (PROMISING, WORSE)
        for v in (CONSISTENT, None)
    )
    assert edge_verdict((0.5, 3.0), (0.1, 2.0)).startswith("positive in both")
    assert edge_verdict((-0.5, 3.0), (0.1, 2.0)) == "edge not demonstrated"


# --- a whole study on the synthetic week ------------------------------------------------------

SMALL_PLAN = """
[study]
name = "test-study"
seed = 1
bootstrap_resamples = 200
block_length = 2
alpha = 0.05
holm_family = ["V1a", "V3"]

[periods.development]
start = "2025-08-04"
end = "2025-08-07"

[periods.validation]
start = "2025-08-08"
end = "2025-08-14"

[forward_holdout]
first_entry = "2025-08-15"
min_trades = 52
latest_evaluation = "2026-08-15"

[baseline]
entry_days_before_expiry = 3
lots = 1
brokerage_per_order_rs = 20.0
slippage_points_per_leg = 0.5
capital_rs = 500000.0
reference_run = "none"

[thresholds]
vix_p33 = 14.0
vix_p67 = 16.0

[[variants]]
id = "B0"
role = "baseline"

[[variants]]
id = "V1a"
role = "primary"
vix_min = 16.0

[[variants]]
id = "V3"
role = "primary"
stop_multiple = 1.25

[[variants]]
id = "V3-k2"
role = "sensitivity"
of = "V3"
stop_multiple = 2.0

[cost_grid]
slippage_points_per_leg = [0.5, 1.0]
brokerage_per_order_rs = [20.0]
"""


def test_a_study_runs_end_to_end_and_writes_every_output(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week_with_friday(pe_tuesday=(105.0, 126.0, 104.0)))
    write_index(run.data, {FRI: 25060.0, MON: 25020.0, TUE: 25050.0, WED: 25100.0, THU: 24900.0})
    plan = tmp_path / "plan.toml"
    plan.write_text(SMALL_PLAN)
    prereg = tmp_path / "prereg.md"
    prereg.write_text("test pre-registration\n")

    # Not committed: refused.
    with pytest.raises(StudyError, match="must be committed"):
        run_study(plan, prereg, run.data, run.costs, tmp_path / "studies", log=lambda _: None)

    folder = run_study(
        plan,
        prereg,
        run.data,
        run.costs,
        tmp_path / "studies",
        require_committed=False,
        log=lambda _: None,
    )
    for name in (
        "study.json",
        "comparison.csv",
        "families.csv",
        "cost_grid.csv",
        "regimes.csv",
        "report.md",
    ):
        assert (folder / name).exists(), name
    study = json.loads((folder / "study.json").read_text())
    # 4 variants x 2 periods + 1 extra cost-grid cell x 2 periods = 10 runs, each a run folder.
    assert len(study["runs"]) == 10
    assert len(list((folder / "runs").iterdir())) == 10
    rows = {(r["variant"], r["period"]): r for r in study["comparison"]}
    # V1a needs VIX >= 16 on Friday (15.0): it skips the week; the pair is -B0's result.
    v1a = rows[("V1a", "development")]
    assert (v1a["trades"], v1a["paired_executed"], v1a["paired_scheduled"]) == (0, 0, 1)
    b0 = rows[("B0", "development")]
    assert v1a["paired_mean"] == pytest.approx(-b0["mean_pct_premium_executed"])
    # V3 at 1.25x stops the put out on Tuesday (the hand-computed trade of
    # test_engine_conditions): net Rs 6,961.04898718125.
    assert rows[("V3", "development")]["net_pnl_rs"] == pytest.approx(6961.04898718125)
    assert rows[("V3", "development")]["stop_exits"] == 1
    # One trade cannot support a test: every verdict is inconclusive.
    assert {v["status"] for v in study["verdicts"].values()} == {"inconclusive"}
    assert len(study["plan"]["sha256"]) == 64
    assert len(study["plan"]["preregistration_sha256"]) == 64
    assert "Does the baseline have an edge?" in (folder / "report.md").read_text()
