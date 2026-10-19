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


def option_row(
    trade_day: date,
    expiry: date,
    lot: int | None = 50,
    *,
    strike: float = 22000.0,
    option_type: str = "CE",
    settle: float = 1.0,
) -> dict[str, object]:
    """One normalised option row with harmless default prices (for hand-built Parquet)."""
    return {
        "trade_date": trade_day, "underlying": "NIFTY", "expiry": expiry, "strike": strike,
        "option_type": option_type, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
        "settle_price": settle, "contracts": 1, "turnover_rs": 1.0, "open_interest": 1,
        "change_in_oi": 0, "lot_size": lot, "underlying_price": 22000.0,
        "zero_volume": False, "source_format": "udiff", "lot_size_source": "udiff",
    }  # fmt: skip


def write_processed(cfg: DataConfig, rows: list[dict[str, object]]) -> None:
    """Store hand-built rows as the per-day Parquet files `build` would have written."""
    import pandas as pd

    from nifty_backtest.marketdata.store import processed_path

    frame = pd.DataFrame(rows).astype({"lot_size": "Int64"})
    for day, part in frame.groupby("trade_date"):
        path = processed_path(cfg, day)  # type: ignore[arg-type]
        path.parent.mkdir(parents=True, exist_ok=True)
        part.to_parquet(path, index=False)


def write_special_sessions(directory: Path, rows: list[tuple[str, str, str]]) -> None:
    """A reference/special_sessions.csv with (date, kind, short_session) rows."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["date,kind,short_session,fo_hours,source,source_url"]
    lines += [f"{d},{k},{s},n/a,test source,https://example.invalid" for d, k, s in rows]
    (directory / "special_sessions.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
