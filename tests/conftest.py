"""Shared fixtures.

Two kinds of tests exist (spec §9, rule 5):
- normal tests, run everywhere including CI, using the synthetic files in tests/fixtures/
- `realdata` tests, which read the local NSE cache in data/ and are skipped when it is absent
"""

from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.marketdata.config import DataConfig
from tests.helpers import REPO_DATA


@pytest.fixture
def cfg(tmp_path: Path) -> DataConfig:
    """A config whose data folder is a fresh temporary directory, covering the fixture day."""
    return DataConfig(data_dir=tmp_path / "data", start=date(2024, 2, 1), end=date(2024, 2, 4))


@pytest.fixture
def real_cfg() -> DataConfig:
    """Config pointing at the real local cache; skips the test if there is no cache."""
    if not (REPO_DATA / "raw" / "fo").exists():
        pytest.skip("no local NSE data cache (data/raw/fo); run `nifty-backtest download`")
    return DataConfig(data_dir=REPO_DATA)
