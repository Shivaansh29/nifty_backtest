"""Find saved studies and read them, checking each one (M7).

A study folder is studies/<study_id>/, where study_id looks like
20261027-005848-m7-short-straddle-robustness (timestamp, then the plan's name). It holds:
  study.json   every comparison, verdict and table (written by `nifty-backtest study`)
  runs/        one ordinary run folder per variant, period and cost-grid cell
  *.csv, report.md   flat copies of study.json for reading outside the API

Like RunStore, this only READS: every number is the number in study.json, computed by
nifty_backtest.research. A study's runs are served by a RunStore pointed at its runs/
folder, so they get exactly the same checks and endpoints as top-level runs.
"""

import json
import re
from pathlib import Path

from pydantic import ValidationError

from nifty_backtest.api.errors import ApiError
from nifty_backtest.api.schemas import StudyFile, StudySummary
from nifty_backtest.api.store import RunStore, explain, reject_constant

# Same shape as run_study creates; checking it first also rules out "..", slashes and other
# ways of escaping the studies folder.
STUDY_ID = re.compile(r"^\d{8}-\d{6}-[a-z0-9_-]+$")
STUDY_FILE = "study.json"


class StudyStore:
    def __init__(self, studies_dir: Path) -> None:
        self.studies_dir = studies_dir

    def study_ids(self) -> list[str]:
        """Every study folder, newest first. Anything else in studies/ is ignored."""
        if not self.studies_dir.is_dir():
            return []
        ids = [p.name for p in self.studies_dir.iterdir() if p.is_dir() and STUDY_ID.match(p.name)]
        return sorted(ids, reverse=True)

    def folder(self, study_id: str) -> Path:
        if not STUDY_ID.match(study_id):
            raise ApiError(422, "invalid_request", f"not a study id: {study_id!r}")
        path = self.studies_dir / study_id
        if not path.is_dir():
            raise ApiError(404, "study_not_found", f"no study {study_id} in {self.studies_dir}")
        return path

    def run_store(self, study_id: str) -> RunStore:
        return RunStore(self.folder(study_id) / "runs")

    def study(self, study_id: str) -> StudyFile:
        path = self.folder(study_id) / STUDY_FILE
        if not path.is_file():
            raise ApiError(500, "artifact_invalid", f"{STUDY_FILE} is missing", None, STUDY_FILE)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
            study = StudyFile.model_validate(raw)
        except (ValueError, ValidationError) as exc:
            raise ApiError(
                500, "artifact_invalid", explain(STUDY_FILE, exc), None, STUDY_FILE
            ) from exc
        if study.study_id != study_id:
            raise ApiError(
                500,
                "artifact_invalid",
                f"{STUDY_FILE} belongs to study {study.study_id}, not to this folder",
                None,
                STUDY_FILE,
            )
        unjudged = [v for v in study.plan.holm_family if v not in study.verdicts]
        if unjudged:
            raise ApiError(
                500,
                "artifact_invalid",
                f"{STUDY_FILE} has no verdict for primary variant(s) {', '.join(unjudged)}",
                None,
                STUDY_FILE,
            )
        runs = self.run_store(study_id)
        missing = sorted({r.run_id for r in study.runs} - set(runs.run_ids()))
        if missing:
            raise ApiError(
                500,
                "artifact_invalid",
                f"{STUDY_FILE} lists {len(missing)} run(s) missing from runs/, e.g. {missing[0]}",
                None,
                STUDY_FILE,
            )
        return study

    def summary(self, study_id: str) -> StudySummary:
        """Never raises for a broken study: the problem is listed instead, so one bad folder
        cannot break the study list."""
        try:
            study = self.study(study_id)
        except ApiError as exc:
            return StudySummary(
                study_id=study_id,
                status="invalid",
                problems=[exc.detail],
                name=None,
                created_at=None,
                git_head=None,
                periods=[],
                edge_verdict=None,
                statuses={},
                run_count=None,
            )
        return StudySummary(
            study_id=study_id,
            status="complete",
            problems=[],
            name=study.plan.name,
            created_at=study.created_at,
            git_head=study.plan.git.head,
            periods=study.plan.periods,
            edge_verdict=study.edge.verdict,
            statuses={v: study.verdicts[v].status for v in study.plan.holm_family},
            run_count=len(study.runs),
        )

    def list_studies(self) -> list[StudySummary]:
        return [self.summary(study_id) for study_id in self.study_ids()]
