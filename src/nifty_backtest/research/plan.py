"""Read and check a pre-registered study plan (docs/research/m7_plan.toml).

The plan is the contract: periods, variants, primary settings, grids, seed and decision
parameters are fixed in it BEFORE any variant runs. This module refuses plans that break the
pre-registration's rules:
  - every variant changes exactly one setting: from the baseline, or (with `of`) from the
    variant it is a sensitivity point of; each variant lists all of its non-baseline settings
  - the Holm family is exactly the primary variants
  - development ends before validation starts, and validation ends before the forward
    holdout, so no study can ever touch forward data
"""

import tomllib
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any

from nifty_backtest.costs.model import CostConfig
from nifty_backtest.engine.backtest import RunConfig
from nifty_backtest.engine.conditions import EntryFilter, ExitRule
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.strategies.short_straddle import ShortStraddle

ROLES = {"baseline", "primary", "sensitivity", "realism", "descriptive"}
BASE_SETTINGS = (
    "entry_days_before_expiry",
    "lots",
    "brokerage_per_order_rs",
    "slippage_points_per_leg",
    "capital_rs",
)
CONDITIONS: dict[str, Any] = {  # condition settings and their "off" value
    "strike_reference": "entry_close",
    "vix_min": None,
    "vix_max": None,
    "adx_max": None,
    "skip_scheduled_events": False,
    "stop_multiple": None,
    "take_profit_decay": None,
}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    name: str
    start: date
    end: date


@dataclass(frozen=True)
class Variant:
    id: str
    role: str
    of: str | None
    settings: dict[str, Any] = field(hash=False)  # the full settings: baseline + changes


@dataclass(frozen=True)
class StudyPlan:
    name: str
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
    thresholds: dict[str, float] = field(hash=False)
    variants: tuple[Variant, ...] = ()
    grid_slippage: tuple[float, ...] = ()
    grid_brokerage: tuple[float, ...] = ()

    def variant(self, variant_id: str) -> Variant:
        for v in self.variants:
            if v.id == variant_id:
                return v
        raise KeyError(variant_id)

    @property
    def baseline(self) -> Variant:
        return self.variant("B0")


def _differences(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    return sorted(k for k in a if a[k] != b[k])


def load_plan(path: Path) -> StudyPlan:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    study, base = raw["study"], raw["baseline"]
    baseline = {k: base[k] for k in BASE_SETTINGS} | CONDITIONS
    variants: list[Variant] = []
    known = set(BASE_SETTINGS) | set(CONDITIONS)
    for entry in raw["variants"]:
        changes = {k: v for k, v in entry.items() if k not in ("id", "role", "of")}
        unknown = set(changes) - known
        if unknown:
            raise PlanError(f"variant {entry['id']}: unknown settings {sorted(unknown)}")
        if entry["role"] not in ROLES:
            raise PlanError(f"variant {entry['id']}: unknown role {entry['role']!r}")
        variants.append(Variant(entry["id"], entry["role"], entry.get("of"), baseline | changes))

    ids = [v.id for v in variants]
    if len(ids) != len(set(ids)):
        raise PlanError("variant ids must be unique")
    by_id = {v.id: v for v in variants}
    if "B0" not in by_id or by_id["B0"].role != "baseline" or by_id["B0"].settings != baseline:
        raise PlanError("the plan needs a baseline B0 with no changes")
    for v in variants:
        if v.role == "baseline":
            continue
        parent = by_id.get(v.of) if v.of else by_id["B0"]
        if parent is None:
            raise PlanError(f"variant {v.id}: unknown parent {v.of!r}")
        changed = _differences(v.settings, parent.settings)
        if len(changed) != 1:
            raise PlanError(
                f"variant {v.id} changes {changed or 'nothing'} from {parent.id}; "
                "exactly one change is allowed"
            )

    family = tuple(study["holm_family"])
    primaries = {v.id for v in variants if v.role == "primary"}
    if set(family) != primaries:
        raise PlanError(
            f"Holm family {sorted(family)} must equal the primaries {sorted(primaries)}"
        )

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
    return StudyPlan(
        name=study["name"],
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
        thresholds={k: float(v) for k, v in raw.get("thresholds", {}).items()},
        variants=tuple(variants),
        grid_slippage=tuple(float(x) for x in grid.get("slippage_points_per_leg", [])),
        grid_brokerage=tuple(float(x) for x in grid.get("brokerage_per_order_rs", [])),
    )


def run_config(
    settings: dict[str, Any], period: Period, data: DataConfig, costs: CostConfig
) -> tuple[RunConfig, ShortStraddle]:
    """The engine configuration for one variant in one period."""
    entry_filter = None
    if (
        any(settings[k] not in (None, False) for k in ("vix_min", "vix_max", "adx_max"))
        or (settings["skip_scheduled_events"])
    ):
        entry_filter = EntryFilter(
            vix_min=settings["vix_min"],
            vix_max=settings["vix_max"],
            adx_max=settings["adx_max"],
            skip_scheduled_events=bool(settings["skip_scheduled_events"]),
        )
    exit_rule = None
    if settings["stop_multiple"] is not None or settings["take_profit_decay"] is not None:
        exit_rule = ExitRule(
            stop_multiple=settings["stop_multiple"],
            take_profit_decay=settings["take_profit_decay"],
        )
    cfg = RunConfig(
        data=replace(data, start=period.start, end=period.end),
        costs=replace(
            costs,
            brokerage_per_order_rs=float(settings["brokerage_per_order_rs"]),
            slippage_points_per_leg=float(settings["slippage_points_per_leg"]),
        ),
        capital_rs=float(settings["capital_rs"]),
        entry_filter=entry_filter,
        exit_rule=exit_rule,
        strike_reference=settings["strike_reference"],
    )
    strategy = ShortStraddle(
        entry_days_before_expiry=int(settings["entry_days_before_expiry"]),
        lots=int(settings["lots"]),
    )
    return cfg, strategy
