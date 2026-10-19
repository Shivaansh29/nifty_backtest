"""Settings for downloading and storing market data.

Every date or limit the data layer depends on lives here, in one object, instead of being
scattered through the code as magic numbers (spec §8).
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class DataConfig:
    """Where data lives, which dates to fetch, and how politely to fetch them."""

    data_dir: Path = Path("data")
    # Hand-maintained, sourced reference files (tracked in git).
    reference_dir: Path = Path("reference")

    # Backtest window (spec §2). `end=None` means "up to today".
    start: date = date(2021, 10, 1)
    end: date | None = None

    # Underlyings kept when normalising. Raw files hold every symbol, so adding BANKNIFTY
    # later only means re-running the normaliser, not re-downloading.
    underlyings: tuple[str, ...] = ("NIFTY",)

    # Format cut-over, verified against NSE's archive on 2026-10-09: the last legacy F&O
    # bhavcopy is for 5 Jul 2024 (8 Jul 2024 returns 404); UDiFF files exist from at least
    # 2 Jan 2024. Legacy is the primary source up to its last file, UDiFF after it.
    legacy_last_date: date = date(2024, 7, 5)

    # UDiFF files are also downloaded from this date, so the six months where both formats
    # exist can be compared row by row (spec §4, trap 7).
    udiff_first_date: date = date(2024, 1, 1)

    # Politeness: at least this long between requests to NSE.
    request_delay_seconds: float = 1.0
    timeout_seconds: float = 30.0
    max_attempts: int = 3

    # A 404 for a recent date may only mean "not published yet", so recent 404s are
    # re-checked on the next run. Older 404s are treated as final (no session that day).
    recheck_recent_days: int = 7

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw" / "fo"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed" / "options"

    def end_date(self, today: date) -> date:
        return self.end if self.end is not None else today
