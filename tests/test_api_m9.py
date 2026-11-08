"""API for multi-leg runs (M9 plan §9.5), on the hand-built condor week of test_engine_multileg.

The API computes nothing: legs and leg marks come straight from legs.csv and leg_marks.csv.
A straddle run, which has neither file, gets `legs: null`, never derived legs.
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nifty_backtest.api.app import create_app
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.metrics.summary import write_metrics
from nifty_backtest.strategies.iron_condor import IronCondor
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.test_engine_multileg import THU, condor_week, setup

TRADE_ID = "NIFTY-2025-06-05"


@pytest.fixture
def client(cfg: DataConfig, tmp_path: Path) -> tuple[TestClient, str, str]:
    run = setup(cfg, tmp_path, condor_week(25100.0))
    runs = tmp_path / "runs"
    condor = save_run(run_backtest(run, IronCondor()), run, IronCondor(), runs)
    write_metrics(condor)
    straddle = save_run(run_backtest(run, ShortStraddle()), run, ShortStraddle(), runs)
    settings = ApiSettings(runs_dir=runs, data=run.data, costs=run.costs, today=lambda: THU)
    return TestClient(create_app(settings)), condor.name, straddle.name


def get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def test_condor_run_is_listed_complete(client: tuple[TestClient, str, str]) -> None:
    api, condor, _ = client
    summary = get(api, f"/api/runs/{condor}")
    assert summary["status"] == "complete", summary["problems"]
    assert summary["strategy"] == "iron_condor"


def test_condor_trade_has_reference_columns_and_blank_one_strike_fields(
    client: tuple[TestClient, str, str],
) -> None:
    api, condor, _ = client
    (trade,) = get(api, f"/api/runs/{condor}/trades")
    assert trade["strike"] is None
    assert trade["ce_entry_close"] is None
    assert trade["reference_atm"] == 24500.0
    assert trade["reference_premium_points"] == 250.0
    assert trade["max_loss_points"] == 194.0
    assert trade["pnl_pct_reference_premium_net"] == pytest.approx(-14668.1123456 / 75 / 2.5)


def test_condor_drill_down_serves_every_leg_and_leg_mark(
    client: tuple[TestClient, str, str],
) -> None:
    api, condor, _ = client
    detail = get(api, f"/api/runs/{condor}/trades/{TRADE_ID}")
    legs = detail["legs"]
    assert [leg["leg_id"] for leg in legs] == [
        "sell-CE-24750",
        "sell-PE-24250",
        "buy-CE-25000",
        "buy-PE-24000",
    ]
    assert legs[2]["expiry_status"] == "exercised"
    assert legs[2]["stt_rs"] == pytest.approx(9.375)
    assert sum(leg["pnl_rs_net"] for leg in legs) == pytest.approx(detail["trade"]["pnl_rs_net"])
    assert len(detail["leg_marks"]) == 16
    assert detail["leg_marks"][0]["leg_id"] == "sell-CE-24750"


def test_straddle_drill_down_has_null_legs(client: tuple[TestClient, str, str]) -> None:
    api, _, straddle = client
    (trade,) = get(api, f"/api/runs/{straddle}/trades")
    assert trade["strike"] == 24500.0  # straddle values are served as before
    detail = get(api, f"/api/runs/{straddle}/trades/{trade['trade_id']}")
    assert detail["legs"] is None
    assert detail["leg_marks"] is None


def test_new_runs_record_the_gst_setting_and_per_leg_files(
    client: tuple[TestClient, str, str],
) -> None:
    api, condor, straddle = client
    detail = get(api, f"/api/runs/{condor}")
    assert detail["config"]["run"]["costs"]["gst_on_ipft"] is True  # set by the test setup
    assert detail["config"]["strategy"]["short_multiple"] == 1.0
    assert detail["artifacts"]["legs.csv"] is True
    assert detail["artifacts"]["leg_marks.csv"] is True
    assert get(api, f"/api/runs/{straddle}")["artifacts"]["legs.csv"] is False


def test_condors_cannot_be_launched_from_the_api(client: tuple[TestClient, str, str]) -> None:
    # The launch form and POST /api/runs default to "up to today", so launching a condor
    # could show forward-holdout results (plan §9.5): there is no way to ask for one.
    api, _, _ = client
    response = api.post("/api/runs", json={"strategy": "iron_condor"})
    assert response.status_code == 422


def test_condors_cannot_be_launched_from_the_cli(capsys: pytest.CaptureFixture[str]) -> None:
    from nifty_backtest.cli import main

    with pytest.raises(SystemExit):
        main(["backtest", "--strategy", "iron_condor"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_an_m9_study_is_served_with_q1_q3_and_sensitivities(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    from nifty_backtest.marketdata.config import DataConfig
    from tests.test_condor_study import run_small_study

    tmp = tmp_path_factory.mktemp("m9_api")
    folder = run_small_study(DataConfig(data_dir=tmp / "data"), tmp)
    settings = ApiSettings(runs_dir=tmp / "runs", studies_dir=folder.parent, today=lambda: THU)
    api = TestClient(create_app(settings))
    (summary,) = get(api, "/api/studies")
    assert summary["status"] == "complete", summary["problems"]
    assert set(summary["statuses"]) == {"C1", "C2", "C3"}
    study = get(api, f"/api/studies/{folder.name}")
    assert study["plan"]["schema_version"] == 2
    assert study["plan"]["gst_on_ipft"] is True
    assert study["plan"]["assumptions"]["stamp_on_cash_exercise"]["status"] == (
        "modelling_assumption_unverified"
    )
    assert {r["variant"] for r in study["q1"]} == {"B0", "C1", "C2", "C3"}
    assert {r["sensitivity"] for r in study["sensitivities"]} == {"stamp", "notional", "gst"}
    assert study["trace"]["bought_leg_in_the_money"] == "NIFTY-2025-06-05"
    c1 = next(
        r for r in study["comparison"] if (r["variant"], r["period"]) == ("C1", "development")
    )
    assert c1["mean_r_p"] == pytest.approx(-14668.1123456 / 75 / 2.5)
    # The study's own runs are served like any run, legs included.
    run_id = next(r["run_id"] for r in study["runs"] if r["key"] == "C1")
    detail = get(api, f"/api/studies/{folder.name}/runs/{run_id}/trades/NIFTY-2025-06-05")
    assert len(detail["legs"]) == 4


def test_all_legs_of_a_run_are_served_for_the_trade_table(
    client: tuple[TestClient, str, str],
) -> None:
    api, condor, straddle = client
    legs = get(api, f"/api/runs/{condor}/legs")
    assert [leg["strike"] for leg in legs] == [24750.0, 24250.0, 25000.0, 24000.0]
    assert get(api, f"/api/runs/{straddle}/legs") == []  # no legs.csv: nothing derived
