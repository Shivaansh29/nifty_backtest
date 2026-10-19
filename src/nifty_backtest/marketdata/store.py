"""Store normalised option rows as Parquet and query them with DuckDB.

Layout: one Parquet file per trading day, data/processed/options/<year>/<YYYY-MM-DD>.parquet.
One file per day keeps rebuilding incremental (only new days are parsed) and lets DuckDB
read the whole history with a single glob pattern, without loading it into memory first.
"""

import logging
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from nifty_backtest.marketdata.bhavcopy import parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import calendar_days
from nifty_backtest.marketdata.lots import fill_lot_sizes
from nifty_backtest.marketdata.sources import primary_format, raw_path

log = logging.getLogger(__name__)


def processed_path(cfg: DataConfig, day: date) -> Path:
    return cfg.processed_dir / f"{day:%Y}" / f"{day.isoformat()}.parquet"


def build(cfg: DataConfig, today: date, rebuild: bool = False) -> tuple[int, int]:
    """Normalise every cached primary-format file that isn't stored yet.

    Returns (days written, days already up to date). A raw file newer than its Parquet
    file (e.g. re-downloaded) is parsed again; `rebuild=True` re-parses everything, which
    is needed after the normalising rules or the reference tables change.
    """
    written = current = 0
    for day in calendar_days(cfg.start, cfg.end_date(today)):
        fmt = primary_format(cfg, day)
        source = raw_path(cfg, fmt, day)
        if not source.exists():
            continue  # no session that day, or not downloaded; the quality report says which
        target = processed_path(cfg, day)
        if not rebuild and target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            current += 1
            continue
        frame = fill_lot_sizes(parse(source, fmt, day, cfg.underlyings), cfg, day)
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False)
        written += 1
        log.info("%s: stored %d rows from %s", day, len(frame), fmt.value)
    return written, current


def connect(cfg: DataConfig) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB session with an `options` view over all stored days."""
    con = duckdb.connect()
    pattern = (cfg.processed_dir / "*" / "*.parquet").as_posix()
    if not any(cfg.processed_dir.glob("*/*.parquet")):
        raise FileNotFoundError(f"no Parquet files under {cfg.processed_dir}; run `build` first")
    con.execute(
        f"CREATE VIEW options AS SELECT * FROM read_parquet('{pattern}', union_by_name = true)"
    )
    return con


def query(cfg: DataConfig, sql: str) -> pd.DataFrame:
    with connect(cfg) as con:
        return con.execute(sql).df()
