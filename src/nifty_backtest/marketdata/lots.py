"""Lot size for every stored option row (spec §4, trap 2).

A lot size belongs to a contract ON a trade date: NSE has changed the lot size of existing
contracts mid-life (e.g. 27 Dec 2024), so it is never looked up by expiry alone.

Where each row's lot size comes from, recorded in `lot_size_source`:
  udiff            the UDiFF file itself (from 8 Jul 2024)
  udiff_same_day   a legacy-format day inside the Jan-Jul 2024 overlap: taken from that day's
                   UDiFF file, contract by contract (both formats were verified to list
                   exactly the same contracts on all 128 overlap days)
  reference_table  earlier legacy days: reference/lot_sizes_legacy.csv, sourced from an NSE circular
  (empty)          no source: the lot size stays empty and M3 skips that week
"""

import csv
from datetime import date
from pathlib import Path

import pandas as pd

from nifty_backtest.marketdata.bhavcopy import BhavcopyError, parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.sources import Format, raw_path

KEY = ["underlying", "expiry", "strike", "option_type"]


def legacy_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if not row["source"].strip():
            raise ValueError(f"{path.name}: every row needs a source")
    return rows


def lot_from_table(table: list[dict[str, str]], underlying: str, day: date) -> int | None:
    matches = [
        int(r["lot_size"])
        for r in table
        if r["underlying"] == underlying
        and date.fromisoformat(r["from_trade_date"])
        <= day
        <= date.fromisoformat(r["to_trade_date"])
    ]
    if len(matches) > 1:
        raise ValueError(f"lot table has overlapping rows for {underlying} on {day}")
    return matches[0] if matches else None


def fill_lot_sizes(frame: pd.DataFrame, cfg: DataConfig, day: date) -> pd.DataFrame:
    """Return `frame` with lot_size filled where a source exists, plus `lot_size_source`."""
    out = frame.copy()
    if (out["source_format"] == Format.UDIFF.value).all():
        out["lot_size_source"] = "udiff"
        return out

    udiff_file = raw_path(cfg, Format.UDIFF, day)
    if udiff_file.exists():
        udiff = parse(udiff_file, Format.UDIFF, day, cfg.underlyings)[[*KEY, "lot_size"]]
        merged = out.drop(columns="lot_size").merge(udiff, on=KEY, how="left", validate="1:1")
        if merged["lot_size"].isna().any():
            raise BhavcopyError(f"{day}: legacy contracts missing from the same day's UDiFF file")
        merged["lot_size_source"] = "udiff_same_day"
        return merged[[*frame.columns, "lot_size_source"]]

    table = legacy_table(cfg.reference_dir / "lot_sizes_legacy.csv")
    lots = {u: lot_from_table(table, u, day) for u in out["underlying"].unique()}
    out["lot_size"] = pd.array([lots[u] for u in out["underlying"]], dtype="Int64")
    out["lot_size_source"] = ["reference_table" if lots[u] else None for u in out["underlying"]]
    return out
