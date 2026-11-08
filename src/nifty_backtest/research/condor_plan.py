"""Read and check a schema-2 study plan (docs/research/m9_plan.toml, M9 plan §9.4).

M7's loader (research/plan.py) is left exactly as it was for files without `schema_version`,
so M7 can still be re-run and its "exactly one change" rule is not weakened. This loader adds
what M9 needs and refuses a plan that breaks the pre-registration:
  - the plan must be frozen (`frozen = true`) before anything runs
  - structures name a known strategy and only that strategy's parameters
  - a primary differs from B0 in its `structure` ONLY; the primaries' structures differ in
    `short_multiple` only
  - realism and sensitivity variants change exactly one setting from their parent (`of`) and
    keep its structure
  - the GST base (`gst_on_ipft`) is set once in [costs] and applies to every run: a variant
    that sets it is refused
  - the Holm family is the primaries; periods are ordered and validation ends before the
    forward holdout; sensitivities name known variants and never change a verdict
"""

import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.research.plan import ROLES, Period, PlanError, Variant
from nifty_backtest.strategies.base import Strategy
from nifty_backtest.strategies.iron_condor import IronCondor
from nifty_backtest.strategies.short_straddle import ShortStraddle

# Strategy -> the parameters a [[structures]] entry may set (a closed list).
STRATEGY_PARAMETERS: dict[str, tuple[str, ...]] = {
    "short_straddle": (),
    "iron_condor": ("short_multiple", "wing_multiple"),
}
SETTINGS: dict[str, Any] = {  # variant settings and the baseline's values for the defaults
    "structure": None,  # from [baseline]
    "entry_days_before_expiry": None,
    "lots": None,
    "brokerage_per_order_rs": None,
    "slippage_points_per_leg": None,
    "capital_rs": None,
    "strike_reference": "entry_close",
}
SENSITIVITIES = ("stamp_sensitivity", "notional_sensitivity", "gst_sensitivity")


@dataclass(frozen=True)
class Structure:
    id: str
    strategy: str
    parameters: dict[str, float] = field(hash=False)


@dataclass(frozen=True)
class CondorPlan:
    name: str
    frozen: bool
    seed: int
    resamples: int
    block_length: int
    alpha: float
    holm_family: tuple[str, ...]
    periods: tuple[Period, ...]  # development, then validation
    forward_first_entry: date
    forward_min_trades: int
    forward_latest_evaluation: date
    reference_run: str
    gst_on_ipft: bool
    structures: dict[str, Structure] = field(hash=False)
    variants: tuple[Variant, ...] = ()
    grid_targets: tuple[str, ...] = ()
    grid_add_promising: bool = True
    grid_slippage: tuple[float, ...] = ()
    grid_brokerage: tuple[float, ...] = ()
    stamp_targets: tuple[str, ...] = ()
    stamp_cases: tuple[str, ...] = ()
    notional_targets: tuple[str, ...] = ()
    notional_cases: tuple[str, ...] = ()
    gst_targets: tuple[str, ...] = ()
    gst_cases: tuple[str, ...] = ()
    trace: dict[str, Any] = field(default_factory=dict, hash=False)
    raw: dict[str, Any] = field(default_factory=dict, hash=False)

    def variant(self, variant_id: str) -> Variant:
        for v in self.variants:
            if v.id == variant_id:
                return v
        raise KeyError(variant_id)

    @property
    def baseline(self) -> Variant:
        return self.variant("B0")


def _structures(raw: dict[str, Any]) -> dict[str, Structure]:
    out: dict[str, Structure] = {}
    for entry in raw.get("structures", []):
        sid, strategy = entry.get("id"), entry.get("strategy")
        if strategy not in STRATEGY_PARAMETERS:
            raise PlanError(f"structure {sid}: unknown strategy {strategy!r}")
        params = {k: v for k, v in entry.items() if k not in ("id", "strategy")}
        unknown = set(params) - set(STRATEGY_PARAMETERS[strategy])
        if unknown:
            raise PlanError(f"structure {sid}: unknown parameters {sorted(unknown)}")
        if sid in out:
            raise PlanError(f"structure ids must be unique ({sid})")
        out[sid] = Structure(sid, strategy, {k: float(v) for k, v in params.items()})
    return out


def load_condor_plan(path: Path, require_frozen: bool = True) -> CondorPlan:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 2:
        raise PlanError(f"{path.name}: schema_version must be 2 for this loader")
    study, base = raw["study"], raw["baseline"]
    frozen = study.get("frozen") is True
    if require_frozen and not frozen:
        raise PlanError(f"{path.name} is not frozen (frozen = false): nothing may run from it")
    structures = _structures(raw)
    baseline = {k: base.get(k, default) for k, default in SETTINGS.items()}
    if baseline["structure"] not in structures:
        raise PlanError(f"baseline structure {baseline['structure']!r} is not declared")

    variants: list[Variant] = []
    for entry in raw["variants"]:
        changes = {k: v for k, v in entry.items() if k not in ("id", "role", "of")}
        if "gst_on_ipft" in changes:
            raise PlanError(
                f"variant {entry['id']}: gst_on_ipft is set once in [costs] for every run"
            )
        unknown = set(changes) - set(SETTINGS)
        if unknown:
            raise PlanError(f"variant {entry['id']}: unknown settings {sorted(unknown)}")
        if entry["role"] not in ROLES:
            raise PlanError(f"variant {entry['id']}: unknown role {entry['role']!r}")
        if "structure" in changes and changes["structure"] not in structures:
            raise PlanError(f"variant {entry['id']}: unknown structure {changes['structure']!r}")
        variants.append(Variant(entry["id"], entry["role"], entry.get("of"), baseline | changes))

    by_id = {v.id: v for v in variants}
    if len(by_id) != len(variants):
        raise PlanError("variant ids must be unique")
    if "B0" not in by_id or by_id["B0"].role != "baseline" or by_id["B0"].settings != baseline:
        raise PlanError("the plan needs a baseline B0 with no changes")
    for v in variants:
        if v.role == "baseline":
            continue
        if v.role == "primary":
            if v.of is not None:
                raise PlanError(f"variant {v.id}: a primary is measured against B0, not `of`")
            changed = sorted(k for k in v.settings if v.settings[k] != baseline[k])
            if changed != ["structure"]:
                raise PlanError(
                    f"variant {v.id} changes {changed or 'nothing'} from B0; a primary may "
                    "differ in its structure only"
                )
            continue
        parent = by_id.get(v.of) if v.of else None
        if parent is None:
            raise PlanError(f"variant {v.id}: needs `of`, a known parent variant")
        if v.settings["structure"] != parent.settings["structure"]:
            raise PlanError(f"variant {v.id}: may not change the structure of {parent.id}")
        changed = sorted(k for k in v.settings if v.settings[k] != parent.settings[k])
        if len(changed) != 1:
            raise PlanError(
                f"variant {v.id} changes {changed or 'nothing'} from {parent.id}; "
                "exactly one change is allowed"
            )

    family = tuple(study["holm_family"])
    primaries = [v for v in variants if v.role == "primary"]
    if set(family) != {v.id for v in primaries}:
        raise PlanError(f"Holm family {sorted(family)} must equal the primaries")
    primary_structures = [structures[v.settings["structure"]] for v in primaries]
    if primary_structures:
        first = primary_structures[0]
        for s in primary_structures[1:]:
            others = {k: x for k, x in s.parameters.items() if k != "short_multiple"}
            first_others = {k: x for k, x in first.parameters.items() if k != "short_multiple"}
            if s.strategy != first.strategy or others != first_others:
                raise PlanError("the primaries' structures must differ in short_multiple only")

    periods = tuple(
        Period(name, date.fromisoformat(p["start"]), date.fromisoformat(p["end"]))
        for name, p in raw["periods"].items()
    )
    if [p.name for p in periods] != ["development", "validation"]:
        raise PlanError("periods must be [development] then [validation]")
    development, validation = periods
    forward = raw["forward_holdout"]
    first_forward = date.fromisoformat(forward["first_entry"])
    if not development.start < development.end < validation.start <= validation.end:
        raise PlanError("development must end before validation starts")
    if validation.end >= first_forward:
        raise PlanError("validation must end before the forward holdout begins")

    grid = raw.get("cost_grid", {})
    lists: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for section in SENSITIVITIES:
        block = raw.get(section, {})
        if block and block.get("changes_verdict") is not False:
            raise PlanError(f"[{section}] must never change a verdict (changes_verdict = false)")
        cases = block.get("cases", [])
        names = tuple(c["basis"] if isinstance(c, dict) else c for c in cases)
        lists[section] = (tuple(block.get("targets", [])), names)
    for name, targets in [("cost_grid", tuple(grid.get("targets", [])))] + [
        (s, lists[s][0]) for s in SENSITIVITIES
    ]:
        unknown = set(targets) - set(by_id)
        if unknown:
            raise PlanError(f"[{name}] has unknown target {sorted(unknown)}")

    return CondorPlan(
        name=study["name"],
        frozen=frozen,
        seed=int(study["seed"]),
        resamples=int(study["bootstrap_resamples"]),
        block_length=int(study["block_length"]),
        alpha=float(study["alpha"]),
        holm_family=family,
        periods=periods,
        forward_first_entry=first_forward,
        forward_min_trades=int(forward["min_trades"]),
        forward_latest_evaluation=date.fromisoformat(forward["latest_evaluation"]),
        reference_run=str(base["reference_run"]),
        gst_on_ipft=bool(raw.get("costs", {}).get("gst_on_ipft", False)),
        structures=structures,
        variants=tuple(variants),
        grid_targets=tuple(grid.get("targets", [])),
        grid_add_promising=bool(grid.get("add_promising_primaries", True)),
        grid_slippage=tuple(float(x) for x in grid.get("slippage_points_per_leg", [])),
        grid_brokerage=tuple(float(x) for x in grid.get("brokerage_per_order_rs", [])),
        stamp_targets=lists["stamp_sensitivity"][0],
        stamp_cases=lists["stamp_sensitivity"][1],
        notional_targets=lists["notional_sensitivity"][0],
        notional_cases=lists["notional_sensitivity"][1],
        gst_targets=lists["gst_sensitivity"][0],
        gst_cases=lists["gst_sensitivity"][1],
        trace=dict(raw.get("trade_trace", {})),
        raw=raw,
    )


def build_strategy(plan: CondorPlan, settings: dict[str, Any]) -> Strategy:
    structure = plan.structures[settings["structure"]]
    days, lots = int(settings["entry_days_before_expiry"]), int(settings["lots"])
    if structure.strategy == "short_straddle":
        return ShortStraddle(entry_days_before_expiry=days, lots=lots)
    return IronCondor(
        short_multiple=structure.parameters["short_multiple"],
        wing_multiple=structure.parameters["wing_multiple"],
        entry_days_before_expiry=days,
        lots=lots,
    )


def run_config(
    plan: CondorPlan,
    settings: dict[str, Any],
    period: Period,
    data: DataConfig,
    costs: CostConfig,
) -> tuple[RunConfig, Strategy]:
    """The engine configuration for one variant in one period. The GST base is the plan's,
    for every run, so both sides of every pair share it."""
    cfg = RunConfig(
        data=replace(data, start=period.start, end=period.end),
        costs=replace(
            costs,
            brokerage_per_order_rs=float(settings["brokerage_per_order_rs"]),
            slippage_points_per_leg=float(settings["slippage_points_per_leg"]),
            gst_on_ipft=plan.gst_on_ipft,
        ),
        capital_rs=float(settings["capital_rs"]),
        strike_reference=settings["strike_reference"],
    )
    return cfg, build_strategy(plan, settings)
