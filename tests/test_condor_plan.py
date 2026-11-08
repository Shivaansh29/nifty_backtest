"""The schema-2 study plan loader (M9 plan §9.4) and the frozen M9 plan itself."""

from pathlib import Path

import pytest

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.research.condor_plan import load_condor_plan, run_config
from nifty_backtest.research.plan import PlanError, load_plan
from nifty_backtest.strategies.iron_condor import IronCondor
from nifty_backtest.strategies.short_straddle import ShortStraddle

REPO = Path(__file__).resolve().parents[1]
M9_PLAN = REPO / "docs" / "research" / "m9_plan.toml"
M7_PLAN = REPO / "docs" / "research" / "m7_plan.toml"


def test_the_frozen_m9_plan_loads_with_its_registered_contents() -> None:
    plan = load_condor_plan(M9_PLAN)
    assert plan.name == "m9-iron-condor"
    assert plan.seed == 20261106
    assert plan.holm_family == ("C1", "C2", "C3")
    assert [v.id for v in plan.variants] == ["B0", "C1", "C2", "C3", "C1-R"]
    assert plan.variant("C2").settings["structure"] == "condor_m075"
    assert plan.variant("C1-R").settings["strike_reference"] == "previous_close"
    assert plan.gst_on_ipft is True
    assert plan.grid_targets == ("B0", "C1")
    assert plan.grid_slippage == (0.5, 1.0, 2.0)
    assert plan.grid_brokerage == (0.0, 20.0, 40.0)
    assert [p.end.isoformat() for p in plan.periods] == ["2024-09-30", "2026-10-16"]
    assert plan.stamp_cases == ("intrinsic_value_x_quantity", "settlement_level_x_quantity")


def test_the_m7_plan_still_loads_with_the_m7_loader() -> None:
    assert len(load_plan(M7_PLAN).variants) == 25


def test_run_config_builds_each_structure_and_applies_the_gst_setting() -> None:
    plan = load_condor_plan(M9_PLAN)
    dev = plan.periods[0]
    costs = CostConfig()
    cfg, strategy = run_config(plan, plan.variant("C3").settings, dev, DataConfig(), costs)
    assert isinstance(strategy, IronCondor)
    assert (strategy.short_multiple, strategy.wing_multiple) == (1.25, 1.0)
    assert cfg.costs.gst_on_ipft is True
    assert (cfg.data.start, cfg.data.end) == (dev.start, dev.end)
    cfg_b0, b0 = run_config(plan, plan.baseline.settings, dev, DataConfig(), costs)
    assert isinstance(b0, ShortStraddle)
    assert cfg_b0.costs.gst_on_ipft is True  # the same GST base on both sides of every pair
    cfg_r, _ = run_config(plan, plan.variant("C1-R").settings, dev, DataConfig(), costs)
    assert cfg_r.strike_reference == "previous_close"


def plan_text(**replace: str) -> str:
    text = M9_PLAN.read_text(encoding="utf-8")
    for old, new in replace.items():
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("frozen = true", "frozen = false", "not frozen"),
        ("schema_version = 2", "schema_version = 3", "schema_version"),
        # A primary may differ from B0 in its structure only.
        ('id = "C2"\nrole = "primary"\nstructure = "condor_m075"',
         'id = "C2"\nrole = "primary"\nstructure = "condor_m075"\nslippage_points_per_leg = 1.0',
         "structure only"),
        # Realism and sensitivity variants make exactly one change and keep the structure.
        ('of = "C1"\nstructure = "condor_m100"\nstrike_reference = "previous_close"',
         'of = "C1"\nstructure = "condor_m075"\nstrike_reference = "previous_close"',
         "structure"),
        ('of = "C1"\nstructure = "condor_m100"\nstrike_reference = "previous_close"',
         'of = "C1"\nstructure = "condor_m100"\nstrike_reference = "previous_close"\nlots = 2',
         "exactly one change"),
        # The GST base comes from [costs] only, for every run.
        ('id = "C3"\nrole = "primary"\nstructure = "condor_m125"',
         'id = "C3"\nrole = "primary"\nstructure = "condor_m125"\ngst_on_ipft = false',
         "gst_on_ipft"),
        # Structures: a known strategy and a closed list of parameters.
        ('short_multiple = 1.25\nwing_multiple = 1.00',
         'short_multiple = 1.25\nwing_multiple = 1.00\nstop = 2', "unknown"),
        # C1-C3 differ in short_multiple only.
        ('short_multiple = 1.25\nwing_multiple = 1.00',
         'short_multiple = 1.25\nwing_multiple = 1.5', "short_multiple only"),
        ('holm_family = ["C1", "C2", "C3"]', 'holm_family = ["C1", "C2"]', "Holm"),
        ('end = "2026-10-16"', 'end = "2026-10-20"', "forward holdout"),
        ('targets = ["B0", "C1"]', 'targets = ["B0", "C9"]', "unknown target"),
        ("changes_verdict = false\n\n[[stamp_sensitivity",
         "changes_verdict = true\n\n[[stamp_sensitivity", "never change a verdict"),
    ],
)  # fmt: skip
def test_plans_that_break_the_rules_are_refused(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    path = tmp_path / "plan.toml"
    path.write_text(plan_text(**{old: new}), encoding="utf-8")
    with pytest.raises(PlanError, match=message):
        load_condor_plan(path)


def test_an_unfrozen_plan_can_be_checked_but_not_run(tmp_path: Path) -> None:
    path = tmp_path / "plan.toml"
    path.write_text(plan_text(**{"frozen = true": "frozen = false"}), encoding="utf-8")
    plan = load_condor_plan(path, require_frozen=False)
    assert plan.frozen is False
