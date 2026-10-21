"""Save a backtest run so it can be found, inspected and reproduced later (spec §6).

Each run gets its own folder, runs/<run_id>/, containing:
  config.json    every setting the run used, including the cost assumptions
  manifest.json  git commit, data date range, trading-day count, and SHA-256 fingerprints of
                 the stored data and reference files, so a later re-run can prove it used
                 the same inputs
  trades.csv     the trade log (one row per trade, with context columns)
  marks.csv      daily mark-to-market of every trade
  equity.csv     account value at every close
  skipped.csv    weeks not traded, with the reason
  metrics.json, yearly.csv, monthly.csv, summary.md   performance metrics (M4, metrics/)

Reproducibility (M4, D6): a run asked for "up to today" (end = None) stores the concrete end date
it used, so re-running the saved config reads exactly the same days; and saving from a working
tree with uncommitted changes logs a warning, because the recorded commit would not contain
the code that produced the run.
"""

import dataclasses
import hashlib
import json
import logging
import subprocess
from datetime import date, datetime
from pathlib import Path

from nifty_backtest.engine.backtest import BacktestResult, RunConfig
from nifty_backtest.marketdata.indices import index_path
from nifty_backtest.strategies.base import Strategy

log = logging.getLogger(__name__)


def _jsonable(value: object) -> object:
    if isinstance(value, (Path, date)):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> dict[str, object]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        ).stdout.strip()

    return {
        "commit": git("rev-parse", "HEAD"),
        "uncommitted_changes": bool(git("status", "--porcelain")),
    }


def data_manifest(cfg: RunConfig, result: BacktestResult) -> dict[str, object]:
    """A lightweight fingerprint of everything the run read."""
    stored = sorted(cfg.data.processed_dir.glob("*/*.parquet"))
    # One combined hash over (file name, file hash) pairs: any changed, added or removed
    # day changes it.
    combined = hashlib.sha256()
    for path in stored:
        combined.update(f"{path.name}:{_sha256(path)}\n".encode())
    references = sorted(cfg.data.reference_dir.glob("*.csv"))
    days = result.equity["date"].tolist() if not result.equity.empty else []
    return {
        "first_trading_day": str(days[0]) if days else None,
        "last_trading_day": str(days[-1]) if days else None,
        "trading_day_count": len(days),
        "option_files": len(stored),
        "option_data_sha256": combined.hexdigest(),
        "index_data_sha256": _sha256(index_path(cfg.data)),
        "reference_files_sha256": {p.name: _sha256(p) for p in references},
    }


def resolve_end(cfg: RunConfig, today: date) -> RunConfig:
    """Replace an open-ended window ("up to today") with the concrete date it means."""
    if cfg.data.end is not None:
        return cfg
    return dataclasses.replace(cfg, data=dataclasses.replace(cfg.data, end=today))


def save_run(
    result: BacktestResult,
    cfg: RunConfig,
    strategy: Strategy,
    runs_dir: Path = Path("runs"),
    today: date | None = None,
) -> Path:
    cfg = resolve_end(cfg, today or date.today())
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{strategy.name}"
    folder = runs_dir / run_id
    folder.mkdir(parents=True)
    git = _git_state()
    if git["uncommitted_changes"]:
        log.warning(
            "run %s saved from a working tree with uncommitted changes: the recorded commit %s "
            "does not contain the exact code that produced it",
            run_id,
            str(git["commit"])[:7],
        )
    config = {"run": _jsonable(cfg), "strategy": _jsonable(strategy)}
    manifest = {"run_id": run_id, "git": git, "data": data_manifest(cfg, result)}
    (folder / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result.trades.to_csv(folder / "trades.csv", index=False)
    result.marks.to_csv(folder / "marks.csv", index=False)
    result.equity.to_csv(folder / "equity.csv", index=False)
    result.skipped.to_csv(folder / "skipped.csv", index=False)
    return folder
