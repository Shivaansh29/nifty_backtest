"""Download NSE F&O bhavcopies into the local cache: polite, resumable and logged.

Every calendar date is tried, weekends included, because NSE sometimes trades on weekends and
holidays (e.g. Budget days) and those sessions have bhavcopies too. The outcome for each
(date, format) is appended to a log, so the data-quality report can tell three cases apart:
  ok         the file was downloaded
  not_found  NSE answered 404: no trading session that day (or not published yet)
  error      something went wrong (network, server error, not a zip). Retried on the next run.
"""

import csv
import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.sources import Format, formats_to_download, raw_path, url

log = logging.getLogger(__name__)

# NSE's archive refuses requests that don't look like they come from a browser.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}

# Every .zip file starts with these four bytes. NSE sometimes answers 200 with an HTML error
# page instead of the file, so content is checked, not just the status code.
ZIP_MAGIC = b"PK\x03\x04"

LOG_FIELDS = ["date", "format", "status", "http_status", "bytes", "checked_at"]


@dataclass(frozen=True)
class Outcome:
    status: str  # "ok", "not_found" or "error"
    http_status: int | None
    size: int


def log_path(cfg: DataConfig) -> Path:
    return cfg.raw_dir / "download_log.csv"


def read_log(cfg: DataConfig) -> dict[tuple[date, Format], dict[str, str]]:
    """Latest logged outcome per (date, format). Later lines overwrite earlier ones."""
    path = log_path(cfg)
    latest: dict[tuple[date, Format], dict[str, str]] = {}
    if not path.exists():
        return latest
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            latest[(date.fromisoformat(row["date"]), Format(row["format"]))] = row
    return latest


def _append_log(cfg: DataConfig, day: date, fmt: Format, outcome: Outcome) -> None:
    path = log_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "date": day.isoformat(),
                "format": fmt.value,
                "status": outcome.status,
                "http_status": "" if outcome.http_status is None else outcome.http_status,
                "bytes": outcome.size,
                "checked_at": datetime.now().isoformat(timespec="seconds"),
            }
        )


def needs_download(
    cfg: DataConfig,
    day: date,
    fmt: Format,
    logged: dict[tuple[date, Format], dict[str, str]],
    today: date,
) -> bool:
    """Resume logic: skip what is already cached or known to be a non-trading day."""
    if raw_path(cfg, fmt, day).exists():
        return False
    previous = logged.get((day, fmt))
    if previous is None or previous["status"] == "error":
        return True
    # A logged 404: final if the date is old enough, re-checked if it is recent.
    return (today - day).days <= cfg.recheck_recent_days


def fetch(
    client: httpx.Client, link: str, dest: Path, cfg: DataConfig, sleep: Callable[[float], None]
) -> Outcome:
    """GET one file, retrying temporary failures, and save it atomically.

    The file is first written as `<name>.part` and only renamed once complete, so an
    interrupted run never leaves a half-written file that looks finished.
    """
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            response = client.get(link)
        except httpx.HTTPError as exc:
            log.warning("attempt %d/%d failed for %s: %s", attempt, cfg.max_attempts, link, exc)
            status: int | None = None
        else:
            status = response.status_code
            if status == 404:
                return Outcome("not_found", 404, 0)
            if status == 200:
                if not response.content.startswith(ZIP_MAGIC):
                    log.warning("not a zip file: %s", link)
                    return Outcome("error", 200, len(response.content))
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".part")
                part.write_bytes(response.content)
                os.replace(part, dest)
                return Outcome("ok", 200, len(response.content))
            log.warning("attempt %d/%d: HTTP %d for %s", attempt, cfg.max_attempts, status, link)
        if attempt < cfg.max_attempts:
            sleep(cfg.request_delay_seconds * 2**attempt)  # back off: 2x, 4x, ... the delay
    return Outcome("error", status, 0)


def calendar_days(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


@dataclass
class Summary:
    downloaded: int = 0
    not_found: int = 0
    errors: int = 0
    skipped: int = 0


def download_range(
    cfg: DataConfig,
    client: httpx.Client,
    today: date,
    sleep: Callable[[float], None] = time.sleep,
) -> Summary:
    """Download every missing file between cfg.start and cfg.end (inclusive)."""
    logged = read_log(cfg)
    summary = Summary()
    for day in calendar_days(cfg.start, cfg.end_date(today)):
        for fmt in formats_to_download(cfg, day):
            if not needs_download(cfg, day, fmt, logged, today):
                summary.skipped += 1
                continue
            outcome = fetch(client, url(fmt, day), raw_path(cfg, fmt, day), cfg, sleep)
            _append_log(cfg, day, fmt, outcome)
            if outcome.status == "ok":
                summary.downloaded += 1
                log.info("%s %s: downloaded (%d bytes)", day, fmt.value, outcome.size)
            elif outcome.status == "not_found":
                summary.not_found += 1
                log.info("%s %s: no file (404)", day, fmt.value)
            else:
                summary.errors += 1
                log.error("%s %s: FAILED (will retry next run)", day, fmt.value)
            sleep(cfg.request_delay_seconds)
    return summary


def make_client(cfg: DataConfig) -> httpx.Client:
    return httpx.Client(headers=HEADERS, timeout=cfg.timeout_seconds, follow_redirects=True)
