"""Where each NSE F&O bhavcopy lives online and on disk.

NSE has published the daily F&O bhavcopy in two formats:
- legacy: `fo01OCT2021bhav.csv.zip`, last published for 5 Jul 2024
- UDiFF:  `BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip`, the current format
"""

from datetime import date
from enum import StrEnum
from pathlib import Path

from nifty_backtest.marketdata.config import DataConfig

ARCHIVE = "https://nsearchives.nseindia.com"

# Legacy URLs use upper-case English month abbreviations. They are spelled out here rather
# than produced by strftime("%b"), whose output depends on the computer's language setting.
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


class Format(StrEnum):
    LEGACY = "legacy"
    UDIFF = "udiff"


def file_name(fmt: Format, day: date) -> str:
    if fmt is Format.LEGACY:
        month = _MONTHS[day.month - 1]
        return f"fo{day:%d}{month}{day:%Y}bhav.csv.zip"
    return f"BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def url(fmt: Format, day: date) -> str:
    if fmt is Format.LEGACY:
        month = _MONTHS[day.month - 1]
        return f"{ARCHIVE}/content/historical/DERIVATIVES/{day:%Y}/{month}/{file_name(fmt, day)}"
    return f"{ARCHIVE}/content/fo/{file_name(fmt, day)}"


def raw_path(cfg: DataConfig, fmt: Format, day: date) -> Path:
    """Local cache location, e.g. data/raw/fo/legacy/2021/fo01OCT2021bhav.csv.zip."""
    return cfg.raw_dir / fmt.value / f"{day:%Y}" / file_name(fmt, day)


def primary_format(cfg: DataConfig, day: date) -> Format:
    """The format whose rows become the stored data for this date."""
    return Format.LEGACY if day <= cfg.legacy_last_date else Format.UDIFF


def formats_to_download(cfg: DataConfig, day: date) -> list[Format]:
    """Both formats inside the overlap window, otherwise just the primary one."""
    formats = []
    if day <= cfg.legacy_last_date:
        formats.append(Format.LEGACY)
    if day >= cfg.udiff_first_date:
        formats.append(Format.UDIFF)
    return formats
