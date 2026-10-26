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
    settle: float | None = None,
    close: float = 1.0,
    contracts: int = 1,
) -> dict[str, object]:
    """One normalised option row (for hand-built Parquet). Settle defaults to the close,
    as NSE prints it on non-expiry days."""
    return {
        "trade_date": trade_day, "underlying": "NIFTY", "expiry": expiry, "strike": strike,
        "option_type": option_type, "open": close, "high": close, "low": close, "close": close,
        "settle_price": close if settle is None else settle, "contracts": contracts,
        "turnover_rs": 1.0, "open_interest": 1, "change_in_oi": 0, "lot_size": lot,
        "underlying_price": 22000.0, "zero_volume": contracts == 0, "source_format": "udiff",
        "lot_size_source": "udiff" if lot is not None else None,
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


def write_index(cfg: DataConfig, closes: dict[date, float], vix: float = 15.0) -> None:
    """A hand-built index_daily.parquet: NIFTY close per day, flat VIX and TRI."""
    import pandas as pd

    from nifty_backtest.marketdata.indices import COLUMNS, index_path

    rows = [
        {"date": d, "nifty_open": c, "nifty_high": c, "nifty_low": c, "nifty_close": c,
         "vix_open": vix, "vix_high": vix, "vix_low": vix, "vix_close": vix,
         "nifty_tri": c * 1.4, "nifty_vix_source": "nse_api"}
        for d, c in closes.items()
    ]  # fmt: skip
    path = index_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_parquet(path, index=False)


def write_events(directory: Path, rows: list[tuple[str, str]]) -> None:
    """A reference/events.csv with (date, type) rows."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["date,type,description,source,source_url"]
    lines += [f"{d},{k},test event,test source,https://example.invalid" for d, k in rows]
    (directory / "events.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_scheduled_events(directory: Path, rows: list[tuple[str, str, bool, str, str]]) -> None:
    """A reference/events.csv with M7 columns: (date, type, known_in_advance, announced_on,
    originally_scheduled) rows."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "date,type,description,source,source_url,known_in_advance,announced_on,"
        "originally_scheduled,announcement_source,announcement_url"
    ]
    lines += [
        f"{d},{k},test event,test source,https://example.invalid,{str(known).lower()},{a},{o},"
        "test announcement,https://example.invalid"
        for d, k, known, a, o in rows
    ]
    (directory / "events.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
