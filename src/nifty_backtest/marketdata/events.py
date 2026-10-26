"""Scheduled market events (spec §5): Union Budgets, RBI policy decisions, election results.

Read from reference/events.csv, where every row cites its official source (RBI, the Union
Budget speech, the Election Commission). Every event TAGS the trades whose window holds it.

M7 adds when each date became public, so a filter can use only what was known at the time:
  known_in_advance      false for an unscheduled event (the off-cycle RBI meeting of 4 May
                        2022), which nobody could have planned around
  announced_on          when the event's actual date was first published (primary source in
                        announcement_source / announcement_url)
  originally_scheduled  for a rescheduled meeting, the date in the earlier schedule
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
    known_in_advance: bool = False
    announced_on: date | None = None
    originally_scheduled: date | None = None

    def date_known_on(self, info_day: date) -> date | None:
        """The date this event was publicly expected on, as known at the close of `info_day`,
        or None if it was not known then. If the actual date was published later than
        `info_day`, the originally scheduled date (if any) is what was known."""
        if not self.known_in_advance or self.announced_on is None:
            return None
        if self.announced_on <= info_day:
            return self.day
        return self.originally_scheduled


def load_events(cfg: DataConfig) -> list[Event]:
    path = cfg.reference_dir / "events.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if not row["source"].strip():
            raise ValueError(f"{path.name}: event on {row['date']} has no source")
        if row.get("announced_on") and not row.get("announcement_source", "").strip():
            raise ValueError(f"{path.name}: event on {row['date']} has no announcement source")

    def optional_day(text: str | None) -> date | None:
        return date.fromisoformat(text) if text else None

    return [
        Event(
            date.fromisoformat(r["date"]),
            r["type"],
            r["description"],
            known_in_advance=r.get("known_in_advance") == "true",
            announced_on=optional_day(r.get("announced_on")),
            originally_scheduled=optional_day(r.get("originally_scheduled")),
        )
        for r in rows
    ]


def events_between(events: list[Event], after: date, until: date) -> list[Event]:
    """Events dated strictly after `after` and up to and including `until`.

    For a trade entered at the close of `after`, an event on the entry day itself is already
    in the entry prices (RBI and Budget announcements come during market hours), so only
    later events fall inside the trade window.
    """
    return [e for e in events if after < e.day <= until]


def knowable_events_between(
    events: list[Event], after: date, until: date, info_day: date
) -> list[Event]:
    """Scheduled events that, as known at the close of `info_day`, were expected strictly
    after `after` and up to and including `until` (M7 event filter; no hindsight)."""
    found = []
    for e in events:
        expected = e.date_known_on(info_day)
        if expected is not None and after < expected <= until:
            found.append(e)
    return found
