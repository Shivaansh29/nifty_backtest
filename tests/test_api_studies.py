"""REST API for M7 studies, on a real `run_study` output (the synthetic study of
test_research.py). The API must serve study.json unchanged, serve the study's runs through the
same endpoints as top-level runs, and refuse broken studies with a clear error."""

import json
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nifty_backtest.api.app import create_app
from nifty_backtest.api.settings import ApiSettings
from nifty_backtest.api.store import RunStore
from nifty_backtest.marketdata.config import DataConfig
from tests.test_research import synthetic_study


class StudyApi:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.study_id = folder.name
        self.client = TestClient(
            create_app(ApiSettings(runs_dir=folder.parent / "no-runs", studies_dir=folder.parent))
        )
        self.saved: dict[str, Any] = json.loads((folder / "study.json").read_text())

    def get(self, path: str = "") -> Any:
        return self.client.get(f"/api/studies/{self.study_id}{path}")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic study, built once: its 12 runs take over 12 s, because run ids have
    one-second resolution and the study waits for a new second between runs."""
    base = tmp_path_factory.mktemp("study")
    cfg = DataConfig(data_dir=base / "data", start=date(2024, 2, 1), end=date(2024, 2, 4))
    return synthetic_study(cfg, base)


@pytest.fixture
def api(built: Path, tmp_path: Path) -> StudyApi:
    """A fresh copy per test, so a test may break its copy without affecting the others."""
    return StudyApi(shutil.copytree(built, tmp_path / "studies" / built.name))


def test_study_list_shows_the_verdicts(api: StudyApi) -> None:
    (study,) = api.client.get("/api/studies").json()
    assert study["study_id"] == api.study_id
    assert (study["status"], study["problems"]) == ("complete", [])
    assert study["name"] == "test-study"
    assert study["run_count"] == len(api.saved["runs"]) == 12
    assert study["edge_verdict"] == api.saved["edge"]["verdict"]
    assert study["statuses"] == {"V1a": "inconclusive", "V3": "inconclusive"}
    assert [p["name"] for p in study["periods"]] == ["development", "validation"]


def test_study_detail_is_study_json_as_saved(api: StudyApi) -> None:
    response = api.get()
    assert response.status_code == 200
    served = response.json()
    saved = api.saved
    # Everything but the edge block is the file itself, key for key and value for value.
    for key in ("study_id", "plan", "verdicts", "comparison", "families", "cost_grid"):
        assert served[key] == saved[key], key
    assert served["regimes"] == saved["regimes"]
    assert served["runs"] == saved["runs"]
    # The edge block only changes shape: periods keyed by name become a list.
    assert served["edge"]["verdict"] == saved["edge"]["verdict"]
    for period in served["edge"]["periods"]:
        name = period.pop("period")
        assert period == saved["edge"][name]


def test_rows_without_paired_statistics_leave_them_out(api: StudyApi) -> None:
    rows = {(r["variant"], r["period"]): r for r in api.get().json()["comparison"]}
    # The baseline is not compared with itself; nothing is invented for it.
    assert not any(key.startswith("paired_") for key in rows[("B0", "development")])
    # Only primaries in development get a Holm-adjusted p-value.
    assert "paired_p_holm" in rows[("V3", "development")]
    assert "paired_p_holm" not in rows[("V3", "validation")]
    assert "paired_p_holm" not in rows[("V3-k2", "development")]


def test_study_runs_are_served_like_top_level_runs(api: StudyApi) -> None:
    run_id = next(r["run_id"] for r in api.saved["runs"] if r["key"] == "V3")
    direct = RunStore(api.folder / "runs")
    assert api.get(f"/runs/{run_id}/metrics").json()["run_id"] == run_id
    trades = api.get(f"/runs/{run_id}/trades").json()
    assert trades == [t.model_dump(mode="json", exclude_unset=True) for t in direct.trades(run_id)]
    trade_id = trades[0]["trade_id"]
    detail = api.get(f"/runs/{run_id}/trades/{trade_id}").json()
    assert detail["trade"]["pe_exit_reason"] == "stop"  # the hand-computed stop of V3
    for suffix in ("", "/daily", "/yearly", "/monthly", "/equity", "/skipped"):
        assert api.get(f"/runs/{run_id}{suffix}").status_code == 200, suffix
    # A run with no trades is served as such (V1a skipped the only week).
    v1a = next(r["run_id"] for r in api.saved["runs"] if r["key"] == "V1a")
    assert api.get(f"/runs/{v1a}/trades").json() == []
    assert api.get(f"/runs/{v1a}/metrics").json()["error"] == "metrics_not_computed"


def test_unknown_or_malformed_ids(api: StudyApi) -> None:
    missing = api.client.get("/api/studies/20990101-000000-none")
    assert (missing.status_code, missing.json()["error"]) == (404, "study_not_found")
    run = api.get("/runs/20990101-000000-short_straddle")
    assert (run.status_code, run.json()["error"]) == (404, "run_not_found")
    # A run of another study, or a top-level run, is not reachable through this study.
    no_study = api.client.get("/api/studies/20990101-000000-none/runs/20990101-000000-x")
    assert no_study.json()["error"] == "study_not_found"
    for bad in ("..", "abc", "20261027-005848-UPPER"):
        assert api.client.get(f"/api/studies/{bad}").status_code in (404, 422), bad


def _edit_study(edit: Callable[[dict[str, Any]], None]) -> Callable[[Path], None]:
    def apply(folder: Path) -> None:
        path = folder / "study.json"
        study = json.loads(path.read_text())
        edit(study)
        path.write_text(json.dumps(study))

    return apply


def _delete_first_run(folder: Path) -> None:
    study = json.loads((folder / "study.json").read_text())
    shutil.rmtree(folder / "runs" / study["runs"][0]["run_id"])


BROKEN: dict[str, tuple[Callable[[Path], object], str]] = {
    "missing study.json": (lambda f: (f / "study.json").unlink(), "study.json is missing"),
    "not JSON": (lambda f: (f / "study.json").write_text("{"), "study.json:"),
    "NaN in the file": (
        lambda f: (f / "study.json").write_text(
            (f / "study.json").read_text().replace('"alpha": 0.05', '"alpha": NaN')
        ),
        "non-standard JSON value NaN",
    ),
    "unknown field": (_edit_study(lambda s: s.update(extra=1)), "extra"),
    "wrong study id": (
        _edit_study(lambda s: s.update(study_id="20990101-000000-other")),
        "belongs to study 20990101-000000-other",
    ),
    "missing verdict": (
        _edit_study(lambda s: s["verdicts"].pop("V3")),
        "no verdict for primary variant(s) V3",
    ),
    "missing run folder": (_delete_first_run, "missing from runs/"),
}


@pytest.mark.parametrize("case", BROKEN)
def test_broken_studies_are_500_and_the_list_still_works(api: StudyApi, case: str) -> None:
    breaks, message = BROKEN[case]
    breaks(api.folder)
    response = api.get()
    assert response.status_code == 500
    assert response.json()["error"] == "artifact_invalid"
    assert response.json()["artifact"] == "study.json"
    assert message in response.json()["detail"]
    (listed,) = api.client.get("/api/studies").json()
    assert listed["status"] == "invalid"
    assert message in listed["problems"][0]


def test_no_studies_folder_is_an_empty_list(tmp_path: Path) -> None:
    client = TestClient(create_app(ApiSettings(studies_dir=tmp_path / "none")))
    assert client.get("/api/studies").json() == []
