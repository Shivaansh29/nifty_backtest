"""Scheduled market events (spec §5): Union Budgets, RBI policy decisions, election results.

Read from reference/events.csv, where every row cites its official source (RBI, the Union
Budget speech, the Election Commission). Used only to TAG trades for later analysis; v1
never uses events to decide anything.
"""

import csv
from dataclasses import dataclass
from datetime import date

from nifty_backtest.marketdata.config import DataConfig


@dataclass(frozen=True)
class Event:
    day: date
    type: str
    description: str


def load_events(cfg: DataConfig) -> list[Event]:
    path = cfg.reference_dir / "events.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if not row["source"].strip():
            raise ValueError(f"{path.name}: event on {row['date']} has no source")
    return [Event(date.fromisoformat(r["date"]), r["type"], r["description"]) for r in rows]


def events_between(events: list[Event], after: date, until: date) -> list[Event]:
    """Events dated strictly after `after` and up to and including `until`.

    For a trade entered at the close of `after`, an event on the entry day itself is already
    in the entry prices (RBI and Budget announcements come during market hours), so only
    later events fall inside the trade window.
    """
    return [e for e in events if after < e.day <= until]
