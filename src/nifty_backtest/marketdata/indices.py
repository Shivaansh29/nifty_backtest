"""Daily NIFTY 50 OHLC, India VIX and NIFTY 50 TRI: download, cache and store.

Sources (all official, verified 2026-10-19):
- NIFTY 50 OHLC: NSE, /api/historicalOR/indicesHistory. Matches NSE's daily archive file
  ind_close_all (e.g. 1 Oct 2021 close 17532.05 in both).
- India VIX OHLC: NSE, /api/historicalOR/vixhistory (1 Oct 2021 matches ind_close_all too).
- NIFTY 50 TRI (total return: dividends reinvested), for the benchmark: NSE Indices Ltd,
  NSE's index subsidiary, niftyindices.com /BackPage/getTotalReturnIndexString. That is the
  request its own historical-data page sends; the site allows at most one year per request.

Gap filler: NSE's price/VIX API has no row for the short DR-drill session of Sat 2 Mar 2024,
while NSE's daily archive file ind_close_all_DDMMYYYY.csv does. For any trading day the API
lacks, that archive file is used and the row is marked nifty_vix_source = "nse_archive".
Caveat: the archive gives VIX closes to 2 decimals (18 May 2024: archive 20.53, API 20.525),
so a gap-filled VIX close can differ from NSE's own full-precision value by up to 0.005.

Everything is fetched ONE CALENDAR MONTH per request: NSE's price API silently cuts long
ranges short (a one-year request returned only 70 rows). Coverage is then checked against
the option trading days in the data-quality report, so a short answer can't go unnoticed.
"""

import io
import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx
import pandas as pd

from nifty_backtest.marketdata.bhavcopy import legacy_date
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import request_with_retries, save_atomically

log = logging.getLogger(__name__)

NSE_API = "https://www.nseindia.com/api/historicalOR"
NIFTYINDICES = "https://www.niftyindices.com"
ARCHIVE = "https://nsearchives.nseindia.com/content/indices"
SERIES = ("nifty", "vix", "tri")
COLUMNS = [
    "date", "nifty_open", "nifty_high", "nifty_low", "nifty_close",
    "vix_open", "vix_high", "vix_low", "vix_close", "nifty_tri", "nifty_vix_source",
]  # fmt: skip


class IndexDataError(ValueError):
    """An API answer doesn't look as expected. Stop and investigate; never guess."""


def months(start: date, end: date) -> Iterator[tuple[date, date]]:
    """(first day, last day) of each calendar month overlapping start..end, clipped to it."""
    first = start.replace(day=1)
    while first <= end:
        following = (first + timedelta(days=32)).replace(day=1)
        yield max(first, start), min(following - timedelta(days=1), end)
        first = following


def cache_path(cfg: DataConfig, series: str, month_start: date) -> Path:
    return cfg.data_dir / "raw" / "index" / series / f"{month_start:%Y-%m}.json"


def _request(
    client: httpx.Client,
    cfg: DataConfig,
    series: str,
    first: date,
    last: date,
    sleep: Callable[[float], None],
) -> httpx.Response | None:
    if series == "tri":
        cinfo = (
            f"{{'name':'NIFTY 50','startDate':'{first:%d-%b-%Y}','endDate':'{last:%d-%b-%Y}',"
            "'indexName':'NIFTY 50'}"
        )
        return request_with_retries(
            client, cfg, sleep, "POST", f"{NIFTYINDICES}/BackPage/getTotalReturnIndexString",
            json={"cinfo": cinfo},
            headers={"Referer": f"{NIFTYINDICES}/reports/historical-data",
                     "X-Requested-With": "XMLHttpRequest"},
        )  # fmt: skip
    endpoint = "vixhistory" if series == "vix" else "indicesHistory"
    params = {"from": f"{first:%d-%m-%Y}", "to": f"{last:%d-%m-%Y}"}
    if series == "nifty":
        params["indexType"] = "NIFTY 50"
    return request_with_retries(client, cfg, sleep, "GET", f"{NSE_API}/{endpoint}", params=params)


@dataclass
class IndexSummary:
    fetched: int = 0
    cached: int = 0
    archive_days: int = 0


def download_indices(
    cfg: DataConfig, client: httpx.Client, today: date, sleep: Callable[[float], None] = time.sleep
) -> IndexSummary:
    """Fetch every month not yet cached. Recent months are re-fetched: they may be incomplete."""
    summary = IndexSummary()
    # niftyindices.com only answers API calls from a browser-like session, so load the page
    # once to receive its cookies (httpx keeps them for the following requests).
    request_with_retries(client, cfg, sleep, "GET", f"{NIFTYINDICES}/reports/historical-data")
    for first, last in months(cfg.start, cfg.end_date(today)):
        for series in SERIES:
            path = cache_path(cfg, series, first)
            recent = (today - last).days <= cfg.recheck_recent_days
            if path.exists() and not recent:
                summary.cached += 1
                continue
            response = _request(client, cfg, series, first, last, sleep)
            if response is None or response.status_code != 200:
                status = None if response is None else response.status_code
                raise IndexDataError(f"{series} {first:%Y-%m}: HTTP {status}")
            rows = _rows(series, response.content, first, last)  # validate before caching
            save_atomically(path, response.content)
            summary.fetched += 1
            log.info("%s %s: %d rows", series, f"{first:%Y-%m}", len(rows))
            sleep(cfg.request_delay_seconds)
    for day in sorted(_trading_days(cfg, today) - _api_price_days(cfg, today)):
        path = archive_path(cfg, day)
        if path.exists():
            continue
        response = request_with_retries(
            client, cfg, sleep, "GET", f"{ARCHIVE}/ind_close_all_{day:%d%m%Y}.csv"
        )
        if response is None or response.status_code != 200:
            log.error("%s: not in the index API and no archive file either", day)
            continue
        _archive_row(response.content, day)  # validate before caching
        save_atomically(path, response.content)
        summary.archive_days += 1
        log.info("%s: index values taken from the NSE archive file", day)
        sleep(cfg.request_delay_seconds)
    return summary


def archive_path(cfg: DataConfig, day: date) -> Path:
    return cfg.data_dir / "raw" / "index" / "archive" / f"ind_close_all_{day:%d%m%Y}.csv"


def _trading_days(cfg: DataConfig, today: date) -> set[date]:
    """Days with a stored-format bhavcopy, i.e. the trading days the index must cover."""
    from nifty_backtest.marketdata.download import calendar_days
    from nifty_backtest.marketdata.sources import primary_format, raw_path

    return {
        d
        for d in calendar_days(cfg.start, cfg.end_date(today))
        if raw_path(cfg, primary_format(cfg, d), d).exists()
    }


def _api_price_days(cfg: DataConfig, today: date) -> set[date]:
    """Days that BOTH the NIFTY and the VIX API months contain."""
    found: dict[str, set[date]] = {"nifty": set(), "vix": set()}
    for first, last in months(cfg.start, cfg.end_date(today)):
        for series in found:
            path = cache_path(cfg, series, first)
            if path.exists():
                found[series] |= set(_rows(series, path.read_bytes(), first, last)["date"])
    return found["nifty"] & found["vix"]


def _archive_row(content: bytes, day: date) -> pd.DataFrame:
    """The NIFTY 50 and India VIX lines of one ind_close_all file, as one row."""
    frame = pd.read_csv(io.BytesIO(content), dtype=str)
    values: dict[str, object] = {"date": day}
    for name, prefix in (("Nifty 50", "nifty"), ("India VIX", "vix")):
        line = frame[frame["Index Name"].str.strip() == name]
        if len(line) != 1:
            raise IndexDataError(f"archive {day}: expected one '{name}' line, found {len(line)}")
        row = line.iloc[0]
        stamp = row["Index Date"].strip()
        if stamp != f"{day:%d-%m-%Y}":
            raise IndexDataError(f"archive {day}: file is dated {stamp}")
        for column, field in (
            ("open", "Open Index Value"), ("high", "High Index Value"),
            ("low", "Low Index Value"), ("close", "Closing Index Value"),
        ):  # fmt: skip
            values[f"{prefix}_{column}"] = float(row[field])
    return pd.DataFrame([values])


def _tri_date(text: str) -> date:
    """niftyindices dates look like '08 Oct 2021'."""
    return legacy_date(text.strip().replace(" ", "-"))


def _rows(series: str, content: bytes, first: date, last: date) -> pd.DataFrame:
    """Parse one cached month into (date, ...) rows and check they are what we asked for."""
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise IndexDataError(f"{series} {first:%Y-%m}: not JSON") from exc
    if series == "tri":
        records = payload if isinstance(payload, list) else []
        names = {r["Index Name"] for r in records}
        frame = pd.DataFrame(
            {
                "date": [_tri_date(r["Date"]) for r in records],
                "nifty_tri": [float(r["TotalReturnsIndex"]) for r in records],
            }
        )
        expected_name = {"Nifty 50"}
    else:
        records = payload.get("data", []) if isinstance(payload, dict) else []
        names = {r["EOD_INDEX_NAME"] for r in records}
        prefix = "vix" if series == "vix" else "nifty"
        frame = pd.DataFrame(
            {
                "date": [legacy_date(r["EOD_TIMESTAMP"]) for r in records],
                f"{prefix}_open": [float(r["EOD_OPEN_INDEX_VAL"]) for r in records],
                f"{prefix}_high": [float(r["EOD_HIGH_INDEX_VAL"]) for r in records],
                f"{prefix}_low": [float(r["EOD_LOW_INDEX_VAL"]) for r in records],
                f"{prefix}_close": [float(r["EOD_CLOSE_INDEX_VAL"]) for r in records],
            }
        )
        expected_name = {"INDIA VIX"} if series == "vix" else {"NIFTY 50"}
    # Compared case-insensitively: niftyindices printed 'NIFTY 50' instead of 'Nifty 50' on
    # 23-24 Dec 2025 only (checked: same dates, no duplicates, values continuous).
    names = {n.upper() for n in names}
    expected_name = {n.upper() for n in expected_name}
    if records and names != expected_name:
        raise IndexDataError(f"{series} {first:%Y-%m}: unexpected index names {names}")
    if not frame.empty and not frame["date"].between(first, last).all():
        raise IndexDataError(f"{series} {first:%Y-%m}: dates outside the requested month")
    if frame["date"].duplicated().any():
        raise IndexDataError(f"{series} {first:%Y-%m}: duplicate dates")
    return frame


def index_path(cfg: DataConfig) -> Path:
    return cfg.data_dir / "processed" / "index_daily.parquet"


def build_indices(cfg: DataConfig, today: date) -> pd.DataFrame:
    """Combine all cached months into one table: one row per date, a column per value."""
    parts: dict[str, list[pd.DataFrame]] = {s: [] for s in SERIES}
    for first, last in months(cfg.start, cfg.end_date(today)):
        for series in SERIES:
            path = cache_path(cfg, series, first)
            if path.exists():
                parts[series].append(_rows(series, path.read_bytes(), first, last))
    tables = [pd.concat(p, ignore_index=True) for p in parts.values() if p]
    if not tables:
        raise FileNotFoundError("no cached index data; run `download-index` first")
    combined = tables[0]
    for table in tables[1:]:
        # Outer join: a date missing from one series stays visible as an empty cell.
        combined = combined.merge(table, on="date", how="outer")
    combined["nifty_vix_source"] = "nse_api"
    archived = [
        _archive_row(p.read_bytes(), date(int(p.stem[-4:]), int(p.stem[-6:-4]), int(p.stem[-8:-6])))
        for p in sorted((cfg.data_dir / "raw" / "index" / "archive").glob("ind_close_all_*.csv"))
    ]
    if archived:
        fill = pd.concat(archived, ignore_index=True).assign(nifty_vix_source="nse_archive")
        # Archive values are used ONLY where the API has no NIFTY/VIX value for that date.
        has_api = combined.set_index("date")["nifty_close"].notna()
        fill = fill[~fill["date"].map(has_api).fillna(False).astype(bool)]
        combined = combined.set_index("date")
        combined = fill.set_index("date").combine_first(combined).reset_index()
    combined = combined.reindex(columns=COLUMNS).sort_values("date").reset_index(drop=True)
    path = index_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)
    return combined
