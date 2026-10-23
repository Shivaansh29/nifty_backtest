"""Generate the dashboard's test fixtures from the REAL API (M6).

The frontend tests must see exactly what the API sends, so instead of hand-writing JSON this
script saves the synthetic test week (tests/test_engine.py: entry Mon 4 Aug 2025, net P&L
Rs 8,852.28050405) as runs, serves them through the FastAPI app, and writes every response
into frontend/src/test/fixtures.ts as typed constants. TypeScript then checks each fixture
against the types generated from the API's OpenAPI schema.

Four runs cover the dashboard's states:
  RUN_ID      complete, with daily.csv
  MISSING_ID  metrics never computed (metrics_missing)
  OLD_ID      metrics written before the M4 correction and before M6: no optional fields,
              no daily.csv
  INVALID_ID  trades.csv lacks a column (invalid)

Things that would differ between machines or runs (run ids, git state, absolute paths, file
hashes) are replaced with fixed values, so regenerating gives the same file on the same
platform. Across platforms a float read back from CSV can differ in its last binary digit, so
tests/test_api.py checks the committed file is current with numbers compared to 12
significant digits.

Regenerate with:  uv run python -m tests.frontend_fixtures
"""

import contextlib
import json
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient

from nifty_backtest.api.app import create_app
from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.launch import launch
from nifty_backtest.api.schemas import ErrorBody, RunRequest
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.api.store import RunStore
from nifty_backtest.engine.backtest import run_backtest
from nifty_backtest.engine.runs import save_run
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.metrics.summary import write_metrics
from nifty_backtest.strategies.short_straddle import ShortStraddle
from tests.test_engine import THU, setup, week

OUTPUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "test" / "fixtures.ts"
RUN_ID = "20250807-160000-short_straddle"
MISSING_ID = "20250807-150000-short_straddle"
OLD_ID = "20250807-140000-short_straddle"
INVALID_ID = "20250807-130000-short_straddle"
TRADE_ID = "NIFTY-2025-08-07"
FIXED_HASH = "synthetic-fixture"
FIXED_GIT = {"commit": "0123456789abcdef0123456789abcdef01234567", "uncommitted_changes": False}


def _edit_json(path: Path, edit: Any) -> None:
    data = json.loads(path.read_text())
    edit(data)
    path.write_text(json.dumps(data, indent=2))


def _fix_manifest(folder: Path) -> None:
    def edit(manifest: dict[str, Any]) -> None:
        manifest["run_id"] = folder.name
        manifest["git"] = FIXED_GIT
        data = manifest["data"]
        data["option_data_sha256"] = data["index_data_sha256"] = FIXED_HASH
        data["reference_files_sha256"] = dict.fromkeys(data["reference_files_sha256"], FIXED_HASH)

    _edit_json(folder / "manifest.json", edit)


def _copy_run(source: Path, run_id: str) -> Path:
    target = source.parent / run_id
    shutil.copytree(source, target)
    _fix_manifest(target)
    if (target / "metrics.json").exists():
        _edit_json(target / "metrics.json", lambda m: m.update(run_id=run_id))
    return target


def _make_runs(runs_dir: Path) -> Any:
    """Save the synthetic week and its three variants; returns the run config used."""
    run = setup(DataConfig(data_dir=Path("data")), Path("."), week())
    saved = save_run(run_backtest(run, ShortStraddle()), run, ShortStraddle(), runs_dir)
    folder = saved.rename(runs_dir / RUN_ID)
    _fix_manifest(folder)
    write_metrics(folder)  # takes run id and git state from the (fixed) manifest

    # The config records where the cost table was read from: an absolute path on this machine.
    def relative_rates(config: dict[str, Any]) -> None:
        config["run"]["costs"]["rates_path"] = "reference/cost_rates.csv"

    _edit_json(folder / "config.json", relative_rates)

    missing = _copy_run(folder, MISSING_ID)
    for name in ("metrics.json", "yearly.csv", "monthly.csv", "daily.csv", "summary.md"):
        (missing / name).unlink()

    old = _copy_run(folder, OLD_ID)
    (old / "daily.csv").unlink()

    def strip_correction_fields(metrics: dict[str, Any]) -> None:
        for block in ("strategy_net", "strategy_gross", "benchmark_nifty50_tri"):
            for key in ("totals_note", "max_drawdown_lower_bound", "max_drawdown_note"):
                metrics[block].pop(key)

    _edit_json(old / "metrics.json", strip_correction_fields)
    for name, columns in (
        ("yearly.csv", ["note", "max_drawdown_lower_bound"]),
        ("monthly.csv", ["note"]),
    ):
        pd.read_csv(old / name).drop(columns=columns).to_csv(old / name, index=False)

    invalid = _copy_run(folder, INVALID_ID)
    trades = pd.read_csv(invalid / "trades.csv")
    trades.drop(columns=["pnl_rs_net"]).to_csv(invalid / "trades.csv", index=False)
    return run


def _error(response: Any) -> dict[str, Any]:
    return {"status": response.status_code, "body": response.json()}


def build() -> str:
    """All fixtures as the text of fixtures.ts."""
    with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
        runs_dir = Path("runs")
        run = _make_runs(runs_dir)
        settings = ApiSettings(runs_dir=runs_dir, data=run.data, costs=run.costs, today=lambda: THU)
        client = TestClient(create_app(settings))

        def get(path: str) -> Any:
            response = client.get(f"/api/runs{path}")
            assert response.status_code == 200, (path, response.text)
            return response.json()

        no_data = TestClient(
            create_app(ApiSettings(runs_dir=runs_dir, data=DataConfig(data_dir=Path("empty"))))
        )
        busy = threading.Lock()
        busy.acquire()
        try:
            launch(RunRequest(), settings, RunStore(runs_dir), busy)
            raise AssertionError("a busy launch must fail")
        except ApiError as exc:
            in_progress = {
                "status": exc.status,
                "body": ErrorBody(error=exc.error, detail=exc.detail).model_dump(),
            }

        fixtures: list[tuple[str, str, Any]] = [
            ("runs", "RunSummary[]", get("")),
            ("detail", "RunDetail", get(f"/{RUN_ID}")),
            ("detailMetricsMissing", "RunDetail", get(f"/{MISSING_ID}")),
            ("detailOld", "RunDetail", get(f"/{OLD_ID}")),
            ("metrics", "Metrics", get(f"/{RUN_ID}/metrics")),
            ("metricsOld", "Metrics", get(f"/{OLD_ID}/metrics")),
            ("yearly", "YearRow[]", get(f"/{RUN_ID}/yearly")),
            ("yearlyOld", "YearRow[]", get(f"/{OLD_ID}/yearly")),
            ("monthly", "MonthRow[]", get(f"/{RUN_ID}/monthly")),
            ("trades", "TradeRecord[]", get(f"/{RUN_ID}/trades")),
            ("tradeDetail", "TradeDetail", get(f"/{RUN_ID}/trades/{TRADE_ID}")),
            ("equity", "EquityPoint[]", get(f"/{RUN_ID}/equity")),
            ("daily", "DailyPoint[]", get(f"/{RUN_ID}/daily")),
            ("skipped", "SkippedWeek[]", get(f"/{RUN_ID}/skipped")),
            ("errorDailyMissing", "ErrorFixture", _error(client.get(f"/api/runs/{OLD_ID}/daily"))),
            (
                "errorMetricsMissing",
                "ErrorFixture",
                _error(client.get(f"/api/runs/{MISSING_ID}/metrics")),
            ),
            (
                "errorInvalidTrades",
                "ErrorFixture",
                _error(client.get(f"/api/runs/{INVALID_ID}/trades")),
            ),
            (
                "errorRunNotFound",
                "ErrorFixture",
                _error(client.get("/api/runs/20990101-000000-short_straddle")),
            ),
            (
                "errorLaunchInvalid",
                "ErrorFixture",
                _error(client.post("/api/runs", json={"lots": 0, "capital_rs": -1})),
            ),
            ("errorLaunchNoData", "ErrorFixture", _error(no_data.post("/api/runs", json={}))),
            ("errorLaunchInProgress", "ErrorFixture", in_progress),
        ]
    for name, _, data in fixtures:
        # The synthetic week skips nothing, so "skipped" is legitimately an empty list.
        assert data or name == "skipped", f"fixture {name} is empty"
    types = sorted(
        {t.removesuffix("[]") for _, t, _ in fixtures} - {"ErrorFixture"} | {"ErrorBody"}
    )
    lines = [
        "// Generated by tests/frontend_fixtures.py from the real API serving the synthetic",
        "// test week (net P&L Rs 8,852.28050405). Do not edit by hand; regenerate with",
        "//   uv run python -m tests.frontend_fixtures",
        "// Run ids, git state, absolute paths and file hashes are replaced by fixed values.",
        "",
        "import type {",
        *[f"  {t}," for t in types],
        '} from "../api/types";',
        "",
        "export interface ErrorFixture {",
        "  status: number;",
        "  body: ErrorBody;",
        "}",
        "",
        f'export const RUN_ID = "{RUN_ID}";',
        f'export const MISSING_ID = "{MISSING_ID}";',
        f'export const OLD_ID = "{OLD_ID}";',
        f'export const INVALID_ID = "{INVALID_ID}";',
        f'export const TRADE_ID = "{TRADE_ID}";',
    ]
    for name, type_name, data in fixtures:
        lines += ["", f"export const {name}: {type_name} = {json.dumps(data, indent=2)};"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUTPUT}")
