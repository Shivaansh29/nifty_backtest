"""The FastAPI application (M5): saved runs over HTTP, plus launching new runs.

Start it with `nifty-backtest serve` and open http://127.0.0.1:8000/docs for the interactive
documentation FastAPI generates from the code below.

Every endpoint lives under /api. GET endpoints only read run folders (see store.py); the one
endpoint that changes anything is POST /api/runs, which creates a NEW run folder exactly as
`nifty-backtest backtest` would. There is no authentication, so the server binds to
localhost unless told otherwise.

M7 adds research studies (`nifty-backtest study`): GET /api/studies lists them, GET
/api/studies/{study_id} serves one study.json, and every run of a study is served under
/api/studies/{study_id}/runs/... by the SAME route functions as /api/runs/..., given a run
store for that study's runs/ folder instead of the top-level one.

Route functions are plain `def`, not `async def`: they read files and run pandas, which would
block an async event loop, so FastAPI runs each one in a worker thread instead.
"""

import json
import threading
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from nifty_backtest import __version__
from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.launch import launch
from nifty_backtest.api.schemas import (
    DailyPoint,
    EquityPoint,
    ErrorBody,
    Health,
    Metrics,
    MonthRow,
    RunDetail,
    RunRequest,
    RunSummary,
    SkippedWeek,
    StudyFile,
    StudySummary,
    TradeDetail,
    TradeRecord,
    YearRow,
)
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.api.store import RUN_ID, RunStore
from nifty_backtest.api.studies import STUDY_ID, StudyStore

RunId = Annotated[
    str,
    PathParam(pattern=RUN_ID.pattern, description="e.g. 20261022-191259-short_straddle"),
]
StudyId = Annotated[
    str,
    PathParam(
        pattern=STUDY_ID.pattern,
        description="e.g. 20261027-005848-m7-short-straddle-robustness",
    ),
]
TradeId = Annotated[
    str, PathParam(pattern=r"^[A-Za-z0-9_.-]+$", description="e.g. NIFTY-2025-06-05")
]


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Document these error statuses (with the ErrorBody shape) in the OpenAPI page."""
    return {status: {"model": ErrorBody} for status in statuses}


def _error_response(status: int, body: ErrorBody) -> JSONResponse:
    return JSONResponse(status_code=status, content=body.model_dump())


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()
    store = RunStore(settings.runs_dir)
    studies = StudyStore(settings.studies_dir)
    launch_lock = threading.Lock()
    app = FastAPI(
        title="NIFTY options backtester API",
        version=__version__,
        description=(
            "Saved backtest runs (config, manifest, trade log, daily marks, equity curve, "
            "metrics, yearly and monthly tables) and launching new runs. Numbers are served "
            "exactly as saved in each run folder; GET requests never recompute anything."
        ),
    )

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        body = ErrorBody(
            error=exc.error, detail=exc.detail, run_id=exc.run_id, artifact=exc.artifact
        )
        return _error_response(exc.status, body)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = [f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()]
        body = ErrorBody(error="invalid_request", detail="; ".join(problems))
        return _error_response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # e.g. a URL that matches no route at all: same JSON shape as every other error.
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error_response(exc.status_code, ErrorBody(error=code, detail=str(exc.detail)))

    @app.get("/api/health", tags=["service"])
    def health() -> Health:
        return Health(status="ok", version=__version__)

    @app.get("/api/runs", tags=["runs"])
    def list_runs() -> list[RunSummary]:
        """Every saved run, newest first, with its status. A broken run folder is listed as
        `invalid` with its problems instead of breaking the list."""
        return store.list_runs()

    @app.post(
        "/api/runs",
        tags=["runs"],
        status_code=201,
        responses=_errors(409, 422, 500, 503),
    )
    def launch_run(request: RunRequest, response: Response) -> RunSummary:
        """Run a short-straddle backtest and save it, as `nifty-backtest backtest` does.
        Waits until the run has finished; with five years of data that takes a while."""
        summary = launch(request, settings, store, launch_lock)
        response.headers["Location"] = f"/api/runs/{summary.run_id}"
        return summary

    def top_level_runs() -> RunStore:
        return store

    def study_runs(study_id: StudyId) -> RunStore:
        return studies.run_store(study_id)  # 404 if there is no such study

    _add_run_routes(app, "/api/runs", top_level_runs, ("runs", "results"))

    @app.get("/api/studies", tags=["studies"])
    def list_studies() -> list[StudySummary]:
        """Every saved study, newest first, with its baseline-edge verdict and the final
        status of each pre-registered primary variant. A broken study folder is listed as
        `invalid` with its problem instead of breaking the list."""
        return studies.list_studies()

    @app.get(
        "/api/studies/{study_id}",
        tags=["studies"],
        responses=_errors(404, 422, 500),
        response_model_exclude_unset=True,  # a field the file lacks is left out, not invented
    )
    def study_detail(study_id: StudyId) -> StudyFile:
        """study.json as saved: the plan and its fingerprints, the baseline's edge, every
        paired comparison with both bootstrap intervals and their envelope, Holm-adjusted
        p-values, the pre-registered verdicts, sensitivity families, cost grid and regime
        tables. Nothing is recomputed."""
        return studies.study(study_id)

    _add_run_routes(app, "/api/studies/{study_id}/runs", study_runs, ("study runs", "study runs"))

    return app


def _add_run_routes(
    app: FastAPI,
    prefix: str,
    store_for: Callable[..., RunStore],
    tags: tuple[str, str],  # OpenAPI page sections: (run detail, run results)
) -> None:
    """The read-only endpoints of one run, under `prefix`/{run_id}. `store_for` is a FastAPI
    dependency returning the RunStore to read from: the top-level runs/ folder, or a study's
    runs/ folder (its own path parameter, study_id, is resolved by FastAPI)."""
    Store = Annotated[RunStore, Depends(store_for)]
    detail_tag, results_tag = tags

    @app.get(
        prefix + "/{run_id}",
        tags=[detail_tag],
        responses=_errors(404, 422, 500),
        response_model_exclude_unset=True,  # config keys a run's file lacks are left out
    )
    def run_detail(run_id: RunId, store: Store) -> RunDetail:
        """Status, full config, manifest (git commit, data fingerprints) and which files the
        run folder holds."""
        return store.detail(run_id)

    @app.get(
        prefix + "/{run_id}/metrics",
        tags=[results_tag],
        responses=_errors(404, 409, 500),
        response_model_exclude_unset=True,  # a field the file lacks is left out, not invented
    )
    def run_metrics(run_id: RunId, store: Store) -> Metrics:
        """metrics.json as saved. 409 if metrics were never computed for this run."""
        return store.metrics(run_id)

    @app.get(
        prefix + "/{run_id}/yearly",
        tags=[results_tag],
        responses=_errors(404, 409, 500),
        response_model_exclude_unset=True,  # a field the file lacks is left out, not invented
    )
    def run_yearly(run_id: RunId, store: Store) -> list[YearRow]:
        return store.yearly(run_id)

    @app.get(
        prefix + "/{run_id}/monthly",
        tags=[results_tag],
        responses=_errors(404, 409, 500),
        response_model_exclude_unset=True,  # a field the file lacks is left out, not invented
    )
    def run_monthly(run_id: RunId, store: Store) -> list[MonthRow]:
        return store.monthly(run_id)

    @app.get(prefix + "/{run_id}/daily", tags=[results_tag], responses=_errors(404, 409, 500))
    def run_daily(run_id: RunId, store: Store) -> list[DailyPoint]:
        """Daily net and gross equity, drawdowns and the NIFTY 50 TRI curve (daily.csv), for
        charts. 409 for runs whose metrics predate daily.csv, with the command that adds it."""
        return store.daily(run_id)

    @app.get(
        prefix + "/{run_id}/trades",
        tags=[results_tag],
        responses=_errors(404, 422, 500),
        response_model_exclude_unset=True,  # M7 columns only when the run has them
    )
    def run_trades(run_id: RunId, store: Store) -> list[TradeRecord]:
        return store.trades(run_id)

    @app.get(
        prefix + "/{run_id}/trades/{trade_id}",
        tags=[results_tag],
        responses=_errors(404, 422, 500),
        response_model_exclude_unset=True,
    )
    def run_trade(run_id: RunId, trade_id: TradeId, store: Store) -> TradeDetail:
        """One trade with its mark-to-market on every day it was held."""
        return store.trade(run_id, trade_id)

    @app.get(prefix + "/{run_id}/equity", tags=[results_tag], responses=_errors(404, 422, 500))
    def run_equity(run_id: RunId, store: Store) -> list[EquityPoint]:
        """The equity curve exactly as saved in equity.csv (net of costs)."""
        return store.equity(run_id)

    @app.get(prefix + "/{run_id}/skipped", tags=[results_tag], responses=_errors(404, 422, 500))
    def run_skipped(run_id: RunId, store: Store) -> list[SkippedWeek]:
        return store.skipped(run_id)


def openapi_json() -> str:
    """The OpenAPI schema as stable, readable JSON (committed for the frontend, M6)."""
    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"
