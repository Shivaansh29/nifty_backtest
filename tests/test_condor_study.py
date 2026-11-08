"""The M9 study runner on two synthetic condor weeks (plan §7, §9.4).

Development: the hand-computed week of test_engine_multileg (entry Mon 2 Jun 2025, expiry
Thu 5 Jun, settlement 25,100: C1 loses Rs 14,668.1123456 with IPFT in the GST base).
Validation: the same prices one week later (entry Mon 9 Jun, expiry Thu 12 Jun), settling at
24,600, between the short strikes. The plan is the frozen M9 plan with only its dates, bootstrap
size and cost grid shrunk to fit; every rule is the real one.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from nifty_backtest.engine.backtest import RunConfig
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.research.analysis import pair
from nifty_backtest.research.condor_study import StudyError, run_condor_study
from tests.helpers import write_index, write_processed
from tests.test_engine_multileg import FRI, MON, THU, TUE, WED, condor_week, setup

M9_PLAN = Path(__file__).resolve().parents[1] / "docs" / "research" / "m9_plan.toml"
WEEK = timedelta(days=7)
C1_DEV_NET = -14668.1123456


def small_plan() -> str:
    text = M9_PLAN.read_text(encoding="utf-8")
    for old, new in {
        'start = "2021-10-01"\nend = "2024-09-30"': 'start = "2025-06-02"\nend = "2025-06-05"',
        'start = "2024-10-01"\nend = "2026-10-16"': 'start = "2025-06-06"\nend = "2025-06-12"',
        'first_entry = "2026-10-17"': 'first_entry = "2025-06-13"',
        'latest_evaluation = "2028-01-31"': 'latest_evaluation = "2026-06-13"',
        "bootstrap_resamples = 10000": "bootstrap_resamples = 200",
        "block_length = 4 ": "block_length = 2 ",
        "slippage_points_per_leg = [0.5, 1.0, 2.0]": "slippage_points_per_leg = [0.5, 1.0]",
        "brokerage_per_order_rs = [0.0, 20.0, 40.0]": "brokerage_per_order_rs = [20.0]",
    }.items():
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def two_weeks(cfg: DataConfig, tmp_path: Path) -> RunConfig:
    run = setup(cfg, tmp_path, condor_week(25100.0))
    second = []
    for row in condor_week(24600.0):
        row = dict(row)
        row["trade_date"] = row["trade_date"] + WEEK  # type: ignore[operator]
        row["expiry"] = row["expiry"] + WEEK  # type: ignore[operator]
        second.append(row)
    write_processed(run.data, second)
    closes = {FRI: 24400.0, MON: 24500.0, TUE: 24450.0, WED: 24400.0, THU: 25100.0}
    closes |= {d + WEEK: c for d, c in closes.items()} | {THU + WEEK: 24600.0}
    write_index(run.data, closes)
    from dataclasses import replace

    return replace(run, data=replace(run.data, end=THU + WEEK))


def run_small_study(cfg: DataConfig, tmp_path: Path, plan_text: str | None = None) -> Path:
    run = two_weeks(cfg, tmp_path)
    plan = tmp_path / "m9_plan.toml"
    plan.write_text(plan_text or small_plan(), encoding="utf-8")
    prereg = tmp_path / "m9_prereg.md"
    prereg.write_text("test pre-registration\n", encoding="utf-8")
    return run_condor_study(
        plan,
        prereg,
        run.data,
        run.costs,
        tmp_path / "studies",
        require_committed=False,
        log=lambda _: None,
    )


@pytest.fixture(scope="module")
def study(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    """One study for the whole module: the tests below only read its outputs."""
    tmp_path = tmp_path_factory.mktemp("condor_study")
    folder = run_small_study(DataConfig(data_dir=tmp_path / "data"), tmp_path)
    return folder, json.loads((folder / "study.json").read_text())


def test_every_output_is_written(study: tuple[Path, dict[str, Any]]) -> None:
    folder, data = study
    for name in (
        "study.json",
        "comparison.csv",
        "q1.csv",
        "q3.csv",
        "cost_grid.csv",
        "sensitivities.csv",
        "report.md",
    ):
        assert (folder / name).exists(), name
    # 5 variants x 2 periods, plus 1 extra grid cell for B0 and for C1 in each period.
    assert len(data["runs"]) == 10 + 4
    assert data["plan"]["schema_version"] == 2
    assert data["plan"]["gst_on_ipft"] is True
    assert [s["id"] for s in data["plan"]["structures"]] == [
        "short_straddle",
        "condor_m100",
        "condor_m075",
        "condor_m125",
    ]


def test_every_run_uses_the_plans_gst_base(study: tuple[Path, dict[str, Any]]) -> None:
    folder, data = study
    for record in data["runs"]:
        config = json.loads((folder / "runs" / record["run_id"] / "config.json").read_text())
        assert config["run"]["costs"]["gst_on_ipft"] is True, record["key"]


def test_c1_development_trade_is_the_hand_computed_one(study: tuple[Path, dict[str, Any]]) -> None:
    _, data = study
    rows = {(r["variant"], r["period"]): r for r in data["comparison"]}
    c1 = rows[("C1", "development")]
    assert c1["net_pnl_rs"] == pytest.approx(C1_DEV_NET)
    assert c1["mean_r_p"] == pytest.approx(C1_DEV_NET / 75 / 250 * 100)
    assert c1["mean_r_ml"] == pytest.approx(C1_DEV_NET / 75 / 194 * 100)
    assert c1["max_loss_hits"] == 1  # settlement beyond the long call: the full wing lost


def test_q1_rows_and_verdicts(study: tuple[Path, dict[str, Any]]) -> None:
    _, data = study
    q1 = {(r["variant"], r["period"]): r for r in data["q1"]}
    assert set(q1) == {
        (v, p) for v in ("B0", "C1", "C2", "C3") for p in ("development", "validation")
    }
    assert q1[("C1", "development")]["mean"] == pytest.approx(C1_DEV_NET / 75 / 2.5)
    # One trade per period cannot demonstrate anything.
    assert {r["verdict"] for r in data["q1"]} == {"edge not demonstrated"}


def test_q2_pairs_use_the_baseline_premium(study: tuple[Path, dict[str, Any]]) -> None:
    folder, data = study
    rows = {(r["variant"], r["period"]): r for r in data["comparison"]}
    record = {(r["key"], r["period"]): r["run_id"] for r in data["runs"]}
    b0 = pd.read_csv(folder / "runs" / record[("B0", "development")] / "trades.csv")
    c1 = pd.read_csv(folder / "runs" / record[("C1", "development")] / "trades.csv")
    expected = (
        100 * (c1["pnl_points_net"][0] - b0["pnl_points_net"][0]) / b0["premium_fill_points"][0]
    )
    assert rows[("C1", "development")]["paired_mean"] == pytest.approx(expected)
    assert set(data["verdicts"]) == {"C1", "C2", "C3"}
    assert {v["status"] for v in data["verdicts"].values()} == {"inconclusive"}


def test_c1_r_is_paired_with_c1_in_b0_premium(study: tuple[Path, dict[str, Any]]) -> None:
    folder, data = study
    record = {(r["key"], r["period"]): r["run_id"] for r in data["runs"]}

    def read(key: str) -> pd.DataFrame:
        return pd.read_csv(folder / "runs" / record[(key, "development")] / "trades.csv")

    expected = pair(read("C1"), read("C1-R"), denominator=read("B0")).d_pct
    row = next(
        r for r in data["comparison"] if (r["variant"], r["period"]) == ("C1-R", "development")
    )
    assert row["paired_against"] == "C1"
    assert row["paired_mean"] == pytest.approx(expected[0])


def test_q3_risk_table(study: tuple[Path, dict[str, Any]]) -> None:
    _, data = study
    q3 = {(r["variant"], r["period"]): r for r in data["q3"]}
    c1 = q3[("C1", "development")]
    assert c1["net_pnl_rs"] == pytest.approx(C1_DEV_NET)
    assert c1["worst_trade_rs"] == pytest.approx(C1_DEV_NET)
    assert c1["lot_free_max_drawdown"] > 0
    assert c1["net_over_max_drawdown"] < 0


def test_sensitivities_change_no_verdict_and_are_hand_checked(
    study: tuple[Path, dict[str, Any]],
) -> None:
    _, data = study
    rows = {
        (r["sensitivity"], r["case"], r["variant"], r["period"]): r for r in data["sensitivities"]
    }
    # Stamp on the exercised long call (intrinsic 100, settlement 25,100, quantity 75).
    a = rows[("stamp", "intrinsic_value_x_quantity", "C1", "development")]
    b = rows[("stamp", "settlement_level_x_quantity", "C1", "development")]
    assert a["extra_cost_rs"] == pytest.approx(0.00003 * 100 * 75)
    assert b["extra_cost_rs"] == pytest.approx(0.00003 * 25100 * 75)
    assert a["mean_r_p"] == pytest.approx((C1_DEV_NET - 0.225) / 75 / 2.5)
    # SEBI notional on strike x quantity: the assigned 24,750 CE and exercised 25,000 CE.
    n = rows[("notional", "strike_x_quantity", "C1", "development")]
    assert n["extra_cost_rs"] == pytest.approx(
        0.000001 * 1.18 * 75 * ((24750 - 25100) + (25000 - 25100))
    )
    n_b0 = rows[("notional", "strike_x_quantity", "B0", "development")]
    assert n_b0["extra_cost_rs"] == pytest.approx(0.000001 * 1.18 * 75 * (24500 - 25100))
    # GST base without IPFT: the M3-M7 treatment, so B0's charges drop by 18% of its IPFT.
    g = rows[("gst", "ipft_excluded_from_gst_base", "B0", "development")]
    assert g["extra_cost_rs"] < 0
    # Verdicts are computed on the plan's assumptions; a case only says what it would be.
    assert all(
        r["verdict_changes"] is False for r in data["sensitivities"] if "verdict_changes" in r
    )
    assert {v["status"] for v in data["verdicts"].values()} == {"inconclusive"}


def test_trade_trace_selection_is_picked_by_code(study: tuple[Path, dict[str, Any]]) -> None:
    _, data = study
    assert data["trace"]["bought_leg_in_the_money"] == "NIFTY-2025-06-05"
    assert data["trace"]["no_bought_leg_in_the_money"] is None  # none in development here


def test_no_study_row_is_dated_after_validation(study: tuple[Path, dict[str, Any]]) -> None:
    folder, data = study
    end = date.fromisoformat(data["plan"]["periods"][1]["end"])
    for record in data["runs"]:
        trades = pd.read_csv(folder / "runs" / record["run_id"] / "trades.csv")
        if not trades.empty:
            assert pd.to_datetime(trades["expiry"]).dt.date.max() <= end


def test_report_separates_verdicts_from_descriptions_and_states_assumptions(
    study: tuple[Path, dict[str, Any]],
) -> None:
    folder, _ = study
    report = (folder / "report.md").read_text()
    assert "## Verdicts (pre-registered rule)" in report
    assert "Descriptive only" in report
    assert "not a verified legal fact" in report
    assert "unverified" in report


def test_an_unfrozen_plan_is_refused(cfg: DataConfig, tmp_path: Path) -> None:
    with pytest.raises(StudyError, match="not frozen"):
        run_small_study(cfg, tmp_path, small_plan().replace("frozen = true", "frozen = false"))


def test_plan_files_must_be_committed(cfg: DataConfig, tmp_path: Path) -> None:
    run = two_weeks(cfg, tmp_path)
    plan = tmp_path / "m9_plan.toml"
    plan.write_text(small_plan(), encoding="utf-8")
    prereg = tmp_path / "prereg.md"
    prereg.write_text("x\n", encoding="utf-8")
    with pytest.raises(StudyError, match="must be committed"):
        run_condor_study(plan, prereg, run.data, run.costs, tmp_path / "s", log=lambda _: None)
