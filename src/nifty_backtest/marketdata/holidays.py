"""NSE's official trading-holiday list for the F&O segment, used to check the calendar.

Source: NSE's holiday API (/api/holiday-master?type=trading&year=YYYY), the data behind
nseindia.com's Holidays page; it accepts past years. The data-quality report checks every
weekday without a bhavcopy against this list, so a missing file can't hide as a "holiday".
"""

import json
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx

from nifty_backtest.marketdata.bhavcopy import legacy_date
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import request_with_retries, save_atomically

HOLIDAY_API = "https://www.nseindia.com/api/holiday-master"


def holiday_path(cfg: DataConfig, year: int) -> Path:
    return cfg.data_dir / "raw" / "holidays" / f"{year}.json"


def download_holidays(
    cfg: DataConfig, client: httpx.Client, today: date, sleep: Callable[[float], None] = time.sleep
) -> int:
    """Fetch each year's list; the current year is always refreshed (NSE adds holidays)."""
    fetched = 0
    for year in range(cfg.start.year, cfg.end_date(today).year + 1):
        path = holiday_path(cfg, year)
        if path.exists() and year < today.year:
            continue
        response = request_with_retries(
            client, cfg, sleep, "GET", HOLIDAY_API, params={"type": "trading", "year": year}
        )
        if response is None or response.status_code != 200 or "FO" not in response.json():
            raise ValueError(f"holiday list for {year}: unexpected answer")
        save_atomically(path, response.content)
        fetched += 1
        sleep(cfg.request_delay_seconds)
    return fetched


def fo_holidays(cfg: DataConfig, today: date) -> dict[date, str]:
    """{date: description} for every cached year (F&O segment only)."""
    holidays: dict[date, str] = {}
    for year in range(cfg.start.year, cfg.end_date(today).year + 1):
        path = holiday_path(cfg, year)
        if not path.exists():
            continue
        for item in json.loads(path.read_text(encoding="utf-8"))["FO"]:
            day = legacy_date(item["tradingDate"])  # "15-Jan-2026"; locale-independent
            holidays[day] = item["description"].strip()
    return holidays
