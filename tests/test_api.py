"""REST API (M5) on synthetic runs.

The run is the hand-built week from test_engine.py (entry Mon 4 Aug 2025 at NIFTY 25,020,
lot 75, net P&L Rs 8,852.28050405), saved with save_run and write_metrics exactly as the CLI
saves it. The API must serve those files unchanged, and refuse broken ones with a clear error.
"""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from nifty_backtest.api import launch as launch_module
from nifty_backtest.api.app import create_app
from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.launch import launch
from nifty_backtest.api.schemas import RunRequest
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.api.store import RunStore
from nifty_backtest.cli import main
from nifty_backtest.engine.backtest import RunConfig, run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.metrics.summary import write_metrics
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.test_engine import THU, TUE, WED, setup, week
from tests.test_metrics_run import NET_PER_UNIT

NET_RS = 8852.28050405
TRADE_ID = "NIFTY-2025-08-07"


class Api:
    """A test client plus the run folder it serves."""

    def __init__(self, client: TestClient, folder: Path) -> None:
        self.client, self.folder = client, folder
        self.run_id = folder.name

    def get(self, path: str = "") -> Any:
        return self.client.get(f"/api/runs/{self.run_id}{path}")


def settings_for(run: RunConfig, runs_dir: Path) -> ApiSettings:
    return ApiSettings(runs_dir=runs_dir, data=run.data, costs=run.costs, today=lambda: THU)


@pytest.fixture
def api(cfg: DataConfig, tmp_path: Path) -> Api:
    run = setup(cfg, tmp_path, week())
    folder = save_run(run_backtest(run, ShortStraddle()), run, ShortStraddle(), tmp_path / "runs")
    write_metrics(folder)
    return Api(TestClient(create_app(settings_for(run, tmp_path / "runs"))), folder)


@pytest.fixture
def launcher(cfg: DataConfig, tmp_path: Path) -> TestClient:
    """A client over the same market data but an empty runs folder (for POST /api/runs)."""
    run = setup(cfg, tmp_path, week())
    return TestClient(create_app(settings_for(run, tmp_path / "launched")))


# --- reading a good run ----------------------------------------------------------------


def test_health() -> None:
    assert TestClient(create_app()).get("/api/health").json()["status"] == "ok"


def test_run_list_shows_a_complete_run_with_its_headline(api: Api) -> None:
    runs = api.client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [api.run_id]
    run = runs[0]
    assert (run["status"], run["problems"], run["strategy"]) == ("complete", [], "short_straddle")
    assert run["headline"]["total_pnl_rs"] == pytest.approx(NET_RS)
    assert run["headline"]["roi"] == pytest.approx(NET_RS / 500_000)
    assert (run["headline"]["trades"], run["headline"]["win_rate"]) == (1, 1.0)
    assert (run["first_trading_day"], run["last_trading_day"]) == ("2025-08-04", "2025-08-07")
    assert run["created_at"].startswith(f"{api.run_id[:4]}-{api.run_id[4:6]}-{api.run_id[6:8]}T")


def test_run_list_ignores_other_entries_and_a_missing_folder(api: Api, tmp_path: Path) -> None:
    (api.folder.parent / "notes").mkdir()
    (api.folder.parent / ".DS_Store").write_text("x")
    assert len(api.client.get("/api/runs").json()) == 1
    empty = TestClient(create_app(ApiSettings(runs_dir=tmp_path / "no_such_folder")))
    assert empty.get("/api/runs").json() == []


def test_run_detail(api: Api) -> None:
    detail = api.get().json()
    assert detail["config"]["run"]["capital_rs"] == 500_000
    assert detail["config"]["run"]["data"]["end"] == "2025-08-07"
    assert detail["config"]["strategy"] == {
        "name": "short_straddle",
        "entry_days_before_expiry": 3,
        "lots": 1,
    }
    assert detail["manifest"]["run_id"] == api.run_id
    assert detail["manifest"]["data"]["trading_day_count"] == 4
    assert all(detail["artifacts"].values())
    assert (detail["trade_count"], detail["skipped_count"]) == (1, 0)


def test_metrics_are_served_exactly_as_saved(api: Api) -> None:
    served = api.get("/metrics").json()
    assert served == json.loads((api.folder / "metrics.json").read_text())
    net = served["strategy_net"]
    assert net["total_pnl_rs"] == pytest.approx(NET_RS)
    assert (net["totals_note"], net["max_drawdown_lower_bound"]) == ("", False)
    assert served["benchmark_nifty50_tri"]["roi"] == pytest.approx(24900 / 25020 - 1)
    assert served["trades"]["trades"] == 1


def test_metrics_saved_before_the_m4_correction_are_served_as_saved(api: Api) -> None:
    # Older metrics files lack the correction's fields. The API leaves them out instead of
    # inventing values, so the response is still exactly the file.
    metrics = json.loads((api.folder / "metrics.json").read_text())
    for key in ("totals_note", "max_drawdown_lower_bound", "max_drawdown_note"):
        for block in ("strategy_net", "strategy_gross", "benchmark_nifty50_tri"):
            del metrics[block][key]
    (api.folder / "metrics.json").write_text(json.dumps(metrics))
    yearly = pd.read_csv(api.folder / "yearly.csv").drop(
        columns=["note", "max_drawdown_lower_bound"]
    )
    yearly.to_csv(api.folder / "yearly.csv", index=False)

    assert api.get("/metrics").json() == metrics
    row = api.get("/yearly").json()[0]
    assert "note" not in row
    assert "max_drawdown_lower_bound" not in row
    assert api.client.get("/api/runs").json()[0]["status"] == "complete"


def test_daily_series_are_served_as_saved(api: Api) -> None:
    daily = api.get("/daily").json()
    saved = pd.read_csv(api.folder / "daily.csv")
    assert [d["date"] for d in daily] == saved["date"].tolist()
    assert [d["equity_net_rs"] for d in daily] == saved["equity_net_rs"].tolist()
    assert [d["drawdown_net_pct"] for d in daily] == saved["drawdown_net_pct"].tolist()
    assert daily[-1]["benchmark_equity_rs"] == pytest.approx(500_000 * 24900 / 25020)


def test_runs_saved_before_daily_series_get_a_clear_409(api: Api) -> None:
    # Metrics computed before M6 have no daily.csv. The run is still complete; the endpoint
    # explains how to add the file instead of inventing a series.
    (api.folder / "daily.csv").unlink()
    response = api.get("/daily")
    assert response.status_code == 409
    body = response.json()
    assert (body["error"], body["artifact"]) == ("metrics_not_computed", "daily.csv")
    assert f"nifty-backtest metrics {api.folder}" in body["detail"]
    assert api.client.get("/api/runs").json()[0]["status"] == "complete"
    assert api.get().json()["artifacts"]["daily.csv"] is False


def test_yearly_and_monthly_tables(api: Api) -> None:
    yearly = api.get("/yearly").json()
    assert [row["year"] for row in yearly] == [2025]
    # The column is called "return" in the file and in JSON (return_ is only the Python name).
    assert yearly[0]["return"] == pytest.approx(NET_RS / 500_000)
    assert yearly[0]["note"] is None  # an empty note cell
    monthly = api.get("/monthly").json()
    assert [(row["month"], row["trading_days"]) for row in monthly] == [("2025-08", 4)]


def test_trades_and_single_trade_drill_down(api: Api) -> None:
    trades = api.get("/trades").json()
    assert [t["trade_id"] for t in trades] == [TRADE_ID]
    assert (trades[0]["quantity"], trades[0]["strike"]) == (75, 25000.0)
    assert trades[0]["pnl_rs_net"] == pytest.approx(NET_RS)

    detail = api.get(f"/trades/{TRADE_ID}").json()
    assert detail["trade"] == trades[0]
    marks = detail["marks"]
    assert [m["date"] for m in marks] == ["2025-08-04", "2025-08-05", "2025-08-06", "2025-08-07"]
    # Net rupee mark / 75 = net P&L per unit, worked by hand in test_metrics_run.py.
    assert [m["mtm_rs_net"] / 75 for m in marks] == pytest.approx(NET_PER_UNIT)


def test_equity_curve_and_skipped_weeks(api: Api) -> None:
    equity = api.get("/equity").json()
    assert len(equity) == 4
    assert equity[0]["equity_rs"] == pytest.approx(500_000 + NET_PER_UNIT[0] * 75)
    assert equity[-1]["equity_rs"] == pytest.approx(500_000 + NET_RS)
    assert api.get("/skipped").json() == []


def test_openapi_and_docs_pages() -> None:
    client = TestClient(create_app())
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/health",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/metrics",
        "/api/runs/{run_id}/yearly",
        "/api/runs/{run_id}/monthly",
        "/api/runs/{run_id}/trades",
        "/api/runs/{run_id}/trades/{trade_id}",
        "/api/runs/{run_id}/equity",
        "/api/runs/{run_id}/skipped",
        "/api/runs/{run_id}/daily",
    ):
        assert path in paths
    assert "post" in paths["/api/runs"]
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()


# --- missing things and bad requests -------------------------------------------------------


def test_unknown_run_and_unknown_trade_are_404(api: Api) -> None:
    missing = api.client.get("/api/runs/20991231-000000-short_straddle")
    assert missing.status_code == 404
    assert missing.json() == {
        "error": "run_not_found",
        "detail": f"no run 20991231-000000-short_straddle in {api.folder.parent}",
        "run_id": "20991231-000000-short_straddle",
        "artifact": None,
    }
    trade = api.get("/trades/NIFTY-1999-01-07")
    assert (trade.status_code, trade.json()["error"]) == (404, "trade_not_found")
    route = api.client.get("/api/no_such_endpoint")
    assert (route.status_code, route.json()["error"]) == (404, "not_found")


@pytest.mark.parametrize("bad_id", ["latest", "20261022-191259-Short", "..", "..%2F..%2Fetc"])
def test_malformed_run_ids_are_rejected_before_touching_the_disk(api: Api, bad_id: str) -> None:
    response = api.client.get(f"/api/runs/{bad_id}/trades")
    assert response.status_code in (404, 422)  # 404 when the URL no longer matches a route
    assert response.json()["error"] in ("invalid_request", "not_found")


def test_store_refuses_a_path_outside_the_runs_folder(tmp_path: Path) -> None:
    with pytest.raises(ApiError) as caught:
        RunStore(tmp_path).folder("../../etc")
    assert caught.value.status == 422


def test_run_without_metrics_is_409_and_listed_as_metrics_missing(api: Api) -> None:
    for name in ("metrics.json", "yearly.csv", "monthly.csv"):
        (api.folder / name).unlink()
    for path in ("/metrics", "/yearly", "/monthly"):
        response = api.get(path)
        assert response.status_code == 409
        assert response.json()["error"] == "metrics_not_computed"
        assert "nifty-backtest metrics" in response.json()["detail"]
    run = api.client.get("/api/runs").json()[0]
    assert (run["status"], run["headline"]) == ("metrics_missing", None)
    assert api.get("/trades").status_code == 200  # the trade log itself is fine


def _drop_column(column: str, name: str) -> Callable[[Path], None]:
    def mutate(folder: Path) -> None:
        frame = pd.read_csv(folder / name)
        frame.drop(columns=[column]).to_csv(folder / name, index=False)

    return mutate


def _set_cell(name: str, column: str, value: str) -> Callable[[Path], None]:
    def mutate(folder: Path) -> None:
        frame = pd.read_csv(folder / name).astype({column: object})
        frame.loc[0, column] = value
        frame.to_csv(folder / name, index=False)

    return mutate


def _edit_json(name: str, edit: Callable[[dict[str, Any]], None]) -> Callable[[Path], None]:
    def mutate(folder: Path) -> None:
        data = json.loads((folder / name).read_text())
        edit(data)
        (folder / name).write_text(json.dumps(data))

    return mutate


def _replace_text(name: str, old: str, new: str) -> Callable[[Path], None]:
    def mutate(folder: Path) -> None:
        text = (folder / name).read_text()
        assert old in text
        (folder / name).write_text(text.replace(old, new, 1))

    return mutate


MALFORMED: dict[str, tuple[Callable[[Path], object], str, str, str]] = {
    # case: (how the file is broken, endpoint, artifact named in the error, words in the detail)
    "config is not JSON": (
        lambda f: (f / "config.json").write_text("{not json"),
        "",
        "config.json",
        "config.json",
    ),
    "core file missing": (
        lambda f: (f / "equity.csv").unlink(),
        "/equity",
        "equity.csv",
        "equity.csv is missing",
    ),
    "trade column missing": (
        _drop_column("pnl_rs_net", "trades.csv"),
        "/trades",
        "trades.csv",
        "pnl_rs_net",
    ),
    "wrong type in a cell": (
        _set_cell("trades.csv", "quantity", "seventy-five"),
        "/trades",
        "trades.csv",
        "quantity",
    ),
    "unexpected column": (
        lambda f: (
            pd.read_csv(f / "equity.csv").assign(surprise=1).to_csv(f / "equity.csv", index=False)
        ),
        "/equity",
        "equity.csv",
        "surprise",
    ),
    "manifest of another run": (
        _edit_json("manifest.json", lambda m: m.update(run_id="20200101-000000-other")),
        "/trades",
        "manifest.json",
        "belongs to run 20200101-000000-other",
    ),
    "metrics files incomplete": (
        lambda f: (f / "yearly.csv").unlink(),
        "/metrics",
        "yearly.csv",
        "yearly.csv missing",
    ),
    "stale metrics": (
        _edit_json("metrics.json", lambda m: m["trades"].update(trades=2)),
        "/metrics",
        "metrics.json",
        "does not match this run",
    ),
    "NaN token in metrics.json": (
        _replace_text("metrics.json", '"capital_rs": 500000.0', '"capital_rs": NaN'),
        "/metrics",
        "metrics.json",
        "NaN",
    ),
    "infinity in a CSV": (
        _set_cell("equity.csv", "equity_rs", "inf"),
        "/equity",
        "equity.csv",
        "equity_rs",
    ),
    "daily series malformed": (
        _set_cell("daily.csv", "drawdown_net_pct", "deep"),
        "/daily",
        "daily.csv",
        "drawdown_net_pct",
    ),
    "metrics key missing": (
        _edit_json("metrics.json", lambda m: m["strategy_net"].pop("roi")),
        "/metrics",
        "metrics.json",
        "strategy_net.roi",
    ),
}


@pytest.mark.parametrize("case", MALFORMED)
def test_malformed_artifacts_are_500_and_the_list_still_works(api: Api, case: str) -> None:
    mutate, endpoint, artifact, words = MALFORMED[case]
    mutate(api.folder)

    response = api.get(endpoint)
    assert response.status_code == 500
    body = response.json()
    assert (body["error"], body["artifact"], body["run_id"]) == (
        "artifact_invalid",
        artifact,
        api.run_id,
    )
    assert words in body["detail"]

    listed = api.client.get("/api/runs")
    assert listed.status_code == 200
    run = listed.json()[0]
    assert (run["status"], run["headline"]) == ("invalid", None)
    assert any(words in problem for problem in run["problems"])


def test_missing_values_are_served_as_null_never_nan(api: Api) -> None:
    # The engine leaves a missing mark empty; the API must turn it into null, not NaN
    # (which is not valid JSON).
    marks = pd.read_csv(api.folder / "marks.csv")
    marks.loc[marks["date"] == TUE.isoformat(), ["ce_mark", "mtm_rs_net"]] = float("nan")
    marks.to_csv(api.folder / "marks.csv", index=False)
    equity = pd.read_csv(api.folder / "equity.csv")
    equity.loc[equity["date"] == WED.isoformat(), "equity_rs"] = float("nan")
    equity.to_csv(api.folder / "equity.csv", index=False)

    detail = api.get(f"/trades/{TRADE_ID}")
    tuesday = detail.json()["marks"][1]
    assert (tuesday["ce_mark"], tuesday["mtm_rs_net"]) == (None, None)
    equity_response = api.get("/equity")
    assert equity_response.json()[2]["equity_rs"] is None
    assert "NaN" not in detail.text + equity_response.text


# --- launching a run (POST /api/runs) ------------------------------------------------------


def test_launch_saves_a_complete_run_like_the_cli(launcher: TestClient) -> None:
    response = launcher.post("/api/runs", json={})
    assert response.status_code == 201
    run = response.json()
    assert response.headers["location"] == f"/api/runs/{run['run_id']}"
    assert (run["status"], run["problems"]) == ("complete", [])
    assert run["headline"]["total_pnl_rs"] == pytest.approx(NET_RS)
    detail = launcher.get(response.headers["location"]).json()
    assert detail["config"]["run"]["data"]["end"] == "2025-08-07"  # resolved, not null (D6)
    assert detail["config"]["run"]["costs"]["brokerage_per_order_rs"] == 20.0
    assert [r["run_id"] for r in launcher.get("/api/runs").json()] == [run["run_id"]]


def test_launch_applies_the_requested_parameters(launcher: TestClient) -> None:
    body = {"lots": 2, "brokerage_per_order_rs": 0, "slippage_points_per_leg": 0}
    run_id = launcher.post("/api/runs", json=body).json()["run_id"]
    config = launcher.get(f"/api/runs/{run_id}").json()["config"]
    assert config["strategy"]["lots"] == 2
    assert config["run"]["costs"]["slippage_points_per_leg"] == 0
    trade = launcher.get(f"/api/runs/{run_id}/trades").json()[0]
    assert trade["quantity"] == 150
    # No brokerage or slippage: (220 - 100) points x 150 = Rs 18,000 gross, less statutory
    # charges only.
    assert trade["pnl_rs_gross"] == pytest.approx(18_000)
    assert trade["slippage_rs"] == 0
    assert trade["brokerage_rs"] == 0


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"lots": 0}, "lots"),
        ({"capital_rs": -1}, "capital_rs"),
        ({"slippage_points_per_leg": -0.5}, "slippage_points_per_leg"),
        ({"brokerage_per_order_rs": "free"}, "brokerage_per_order_rs"),
        ({"entry_days_before_expiry": 0}, "entry_days_before_expiry"),
        ({"start": "2025-08-07", "end": "2025-08-04"}, "start must not be after end"),
        ({"end": "07/08/2025"}, "end"),
        ({"stop_loss": 2.0}, "stop_loss"),  # unknown parameters are refused, not ignored
    ],
)
def test_launch_rejects_invalid_parameters(
    launcher: TestClient, body: dict[str, object], words: str
) -> None:
    response = launcher.post("/api/runs", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_request"
    assert words in response.json()["detail"]
    assert launcher.get("/api/runs").json() == []  # nothing was saved


def test_launch_ending_before_the_configured_start_is_422(launcher: TestClient) -> None:
    response = launcher.post("/api/runs", json={"end": "2025-08-01"})  # data starts 4 Aug
    assert (response.status_code, response.json()["error"]) == (422, "invalid_request")


def test_launch_without_market_data_is_503(cfg: DataConfig, tmp_path: Path) -> None:
    client = TestClient(create_app(ApiSettings(runs_dir=tmp_path / "runs", data=cfg)))
    response = client.post("/api/runs", json={})
    assert response.status_code == 503
    assert response.json()["error"] == "data_unavailable"
    assert "nifty-backtest download" in response.json()["detail"]
    assert not (tmp_path / "runs").exists()


def test_launch_with_no_trades_is_saved_without_metrics(launcher: TestClient) -> None:
    # A one-day window holds no expiry, so there is no trade and (like the CLI) no metrics.
    response = launcher.post("/api/runs", json={"start": "2025-08-04", "end": "2025-08-04"})
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "metrics_missing"
    assert launcher.get(f"/api/runs/{run['run_id']}/trades").json() == []
    assert launcher.get(f"/api/runs/{run['run_id']}/equity").json() == [
        {"date": "2025-08-04", "realised_rs": None, "open_mtm_rs": None, "equity_rs": 500000.0}
    ]


def test_only_one_launch_at_a_time(cfg: DataConfig, tmp_path: Path) -> None:
    run = setup(cfg, tmp_path, week())
    settings = settings_for(run, tmp_path / "runs")
    busy = threading.Lock()
    busy.acquire()  # another launch is running
    with pytest.raises(ApiError) as caught:
        launch(RunRequest(), settings, RunStore(settings.runs_dir), busy)
    assert (caught.value.status, caught.value.error) == (409, "run_in_progress")


def test_launch_conflicting_with_an_existing_run_id_is_409(
    launcher: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def same_second(*args: object, **kwargs: object) -> Path:
        raise FileExistsError("runs/20250807-000000-short_straddle")

    monkeypatch.setattr(launch_module, "save_run", same_second)
    response = launcher.post("/api/runs", json={})
    assert (response.status_code, response.json()["error"]) == (409, "run_exists")


def test_launch_reports_an_engine_failure_as_run_failed(
    launcher: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("calendar exploded")

    monkeypatch.setattr(launch_module, "run_backtest", broken)
    response = launcher.post("/api/runs", json={})
    assert response.status_code == 500
    assert response.json() == {
        "error": "run_failed",
        "detail": "RuntimeError: calendar exploded",
        "run_id": None,
        "artifact": None,
    }


# --- the serve command -------------------------------------------------------------------


def test_serve_binds_to_localhost_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    assert main(["serve", "--port", "8123"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123}]


def test_serve_warns_when_exposed_beyond_this_computer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: None)
    main(["serve", "--host", "0.0.0.0"])
    assert "no authentication" in caplog.text


# --- the frontend's copy of the schema (M6) ---------------------------------------------

FRONTEND_SCHEMA = Path(__file__).resolve().parents[1] / "frontend" / "src" / "api" / "openapi.json"


def test_frontend_openapi_schema_is_current() -> None:
    # The dashboard's TypeScript types are generated from this committed file. If the API
    # changes, `uv run nifty-backtest openapi` must be re-run (CI then regenerates the
    # TypeScript types and fails if they differ from the committed ones).
    from nifty_backtest.api.app import openapi_json

    assert FRONTEND_SCHEMA.read_text(encoding="utf-8") == openapi_json(), (
        "frontend/src/api/openapi.json is out of date: run `uv run nifty-backtest openapi`"
    )


def test_frontend_fixtures_are_current() -> None:
    # The dashboard tests use responses recorded from this API (tests/frontend_fixtures.py).
    # Regenerating must give the committed file exactly, so they can never drift from what
    # the API really sends.
    from tests.frontend_fixtures import OUTPUT, build

    assert OUTPUT.read_text(encoding="utf-8") == build(), (
        "frontend/src/test/fixtures.ts is out of date: "
        "run `uv run python -m tests.frontend_fixtures`"
    )
