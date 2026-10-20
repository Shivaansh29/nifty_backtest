"""Trading calendar and expiry calendar, derived from the stored data (spec §4, traps 1 and 6).

Nothing here assumes a weekday. Three facts drive everything:
- A trading day is a day with a bhavcopy. Short special sessions (Muhurat, DR drills), listed
  with their NSE circulars in reference/special_sessions.csv, are trading days but never
  entry days and are not counted in "N trading days before expiry".
- An expiry is REAL only if its contracts traded on that date. NSE re-dates contracts (a
  holiday shift, the Thursday -> Tuesday switch), so a date printed in a file may never arrive.
- On an entry day the nearest contracts may still carry their old, stated expiry date
  (26 Jun 2023 still said 29 Jun; they really expired 28 Jun). The calendar records both
  dates and checks that the stated one is a date that later failed to arrive.
"""

import csv
from dataclasses import dataclass
from datetime import date

import duckdb
import pandas as pd

from nifty_backtest.marketdata.config import DataConfig


@dataclass(frozen=True)
class SpecialSession:
    day: date
    kind: str
    short_session: bool
    source: str


def special_sessions(cfg: DataConfig) -> dict[date, SpecialSession]:
    path = cfg.reference_dir / "special_sessions.csv"
    sessions: dict[date, SpecialSession] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not row["source"].strip():
                raise ValueError(f"{path.name}: every row needs a source")
            if row["short_session"] not in ("true", "false"):
                raise ValueError(f"{path.name}: short_session must be true or false")
            day = date.fromisoformat(row["date"])
            sessions[day] = SpecialSession(
                day, row["kind"], row["short_session"] == "true", row["source"]
            )
    return sessions


def trading_days(con: duckdb.DuckDBPyConnection) -> list[date]:
    rows = con.execute("SELECT DISTINCT trade_date FROM options ORDER BY 1").fetchall()
    return [r[0] for r in rows]


def actual_expiries(con: duckdb.DuckDBPyConnection) -> list[date]:
    """Expiry dates on which their contracts were actually trading."""
    rows = con.execute(
        "SELECT DISTINCT expiry FROM options WHERE trade_date = expiry ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def never_arrived(con: duckdb.DuckDBPyConnection) -> dict[date, date]:
    """{stated expiry: last day it was printed} for stated expiries that never came."""
    rows = con.execute(
        """
        SELECT expiry, max(trade_date) FROM options
        WHERE expiry <= (SELECT max(trade_date) FROM options)
        GROUP BY expiry HAVING NOT bool_or(trade_date = expiry)
        """
    ).fetchall()
    return {r[0]: r[1] for r in rows}


CALENDAR_COLUMNS = [
    "expiry", "expiry_weekday", "entry_date", "entry_weekday", "calendar_days_to_expiry",
    "stated_expiry_on_entry", "relabelled", "lot_size_at_entry", "status",
]  # fmt: skip


def expiry_calendar(
    con: duckdb.DuckDBPyConnection,
    cfg: DataConfig,
    entry_days_before: int,
    expiries_from: date | None = None,
    expiries_to: date | None = None,
) -> pd.DataFrame:
    """One row per real expiry: when to enter, and which contracts to trade that day.

    status:
      ok                    usable
      insufficient_history  the data starts too late to have an entry day
      not_nearest           another real expiry falls between entry and this expiry, so
                            on the entry day this would not be the nearest expiry
      relabel_unexplained   the entry day's nearest contracts carry a different expiry date
                            that is not a known re-dated (never-arrived) date
    """
    if entry_days_before < 1:
        raise ValueError("entry_days_before must be at least 1")
    days = trading_days(con)
    short = {d for d, s in special_sessions(cfg).items() if s.short_session}
    full_days = [d for d in days if d not in short]
    real = actual_expiries(con)
    redated = never_arrived(con)

    rows = []
    for expiry in real:
        if (expiries_from and expiry < expiries_from) or (expiries_to and expiry > expiries_to):
            continue  # outside the requested range; skip the per-expiry queries
        earlier = [d for d in full_days if d < expiry]
        record: dict[str, object] = {"expiry": expiry, "expiry_weekday": f"{expiry:%a}"}
        if len(earlier) < entry_days_before:
            rows.append({**record, "status": "insufficient_history"})
            continue
        entry = earlier[-entry_days_before]
        # On the entry day: the nearest stated expiry strictly after it, and its lot size(s).
        stated, lots = con.execute(
            """
            WITH s AS (SELECT min(expiry) AS e FROM options WHERE trade_date = ? AND expiry > ?)
            SELECT s.e, list(DISTINCT o.lot_size) FILTER (WHERE o.lot_size IS NOT NULL)
            FROM s LEFT JOIN options o ON o.trade_date = ? AND o.expiry = s.e
            GROUP BY s.e
            """,
            [entry, entry, entry],
        ).fetchone() or (None, [])
        nearest_real = min(e for e in real if e > entry)
        if nearest_real != expiry:
            status = "not_nearest"
        elif stated != expiry and redated.get(stated) is None:
            status = "relabel_unexplained"
        else:
            status = "ok"
        rows.append(
            {
                **record,
                "entry_date": entry,
                "entry_weekday": f"{entry:%a}",
                "calendar_days_to_expiry": (expiry - entry).days,
                "stated_expiry_on_entry": stated,
                "relabelled": stated != expiry,
                # One lot size if the day's contracts agree (they always have); else empty.
                "lot_size_at_entry": lots[0] if lots and len(lots) == 1 else None,
                "status": status,
            }
        )
    frame = pd.DataFrame(rows).reindex(columns=CALENDAR_COLUMNS)
    frame["lot_size_at_entry"] = frame["lot_size_at_entry"].astype("Int64")
    return frame
