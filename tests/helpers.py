"""Helpers shared by several test modules."""

import zipfile
from datetime import date
from pathlib import Path

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.sources import Format, raw_path

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_DAY = date(2024, 2, 1)
REPO_DATA = Path(__file__).resolve().parents[1] / "data"


def install_fixture(cfg: DataConfig, fmt: Format, day: date = FIXTURE_DAY) -> Path:
    """Zip a synthetic CSV into the raw cache exactly where a download would have put it."""
    target = raw_path(cfg, fmt, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = FIXTURES / f"synthetic_{fmt.value}_{FIXTURE_DAY.isoformat()}.csv"
    with zipfile.ZipFile(target, "w") as archive:
        archive.write(source, arcname=target.name.removesuffix(".zip"))
    return target
