"""Data-quality report (spec §4): what was loaded, what is missing, and why.

Everything here is counted from the download log, the raw files and the stored Parquet
data. Nothing is estimated. Where M1 cannot yet tell two cases apart (e.g. a weekday with
no session could be a holiday or an NSE gap), the report says so instead of guessing; M2
checks those dates against NSE's official holiday list.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from nifty_backtest.marketdata.bhavcopy import parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.download import read_log
from nifty_backtest.marketdata.sources import Format, primary_format, raw_path
from nifty_backtest.marketdata.store import connect, processed_path

# Columns that must agree exactly when the same day is normalised from both formats.
_SHARED = [
    "trade_date", "underlying", "expiry", "strike", "option_type", "open", "high", "low",
    "close", "settle_price", "contracts", "open_interest", "change_in_oi", "zero_volume",
]  # fmt: skip
# Legacy turnover is only precise to Rs 1,000 (lakhs with 2 decimals).
TURNOVER_TOLERANCE_RS = 1_000.0


@dataclass(frozen=True)
class OverlapResult:
    day: date
    legacy_rows: int
    udiff_rows: int
    matched: int
    mismatched_columns: tuple[str, ...]
    max_turnover_diff_rs: float


def compare_formats(cfg: DataConfig, day: date) -> OverlapResult:
    """Normalise one day from both formats and report every disagreement."""
    legacy = parse(raw_path(cfg, Format.LEGACY, day), Format.LEGACY, day, cfg.underlyings)
    udiff = parse(raw_path(cfg, Format.UDIFF, day), Format.UDIFF, day, cfg.underlyings)
    key = ["underlying", "expiry", "strike", "option_type"]
    both = legacy.merge(udiff, on=key, suffixes=("_l", "_u"))
    mismatched = tuple(
        c for c in _SHARED if c not in key and not (both[f"{c}_l"] == both[f"{c}_u"]).all()
    )
    turnover_diff = (both["turnover_rs_l"] - both["turnover_rs_u"]).abs().max()
    if turnover_diff > TURNOVER_TOLERANCE_RS:
        mismatched += ("turnover_rs",)
    return OverlapResult(day, len(legacy), len(udiff), len(both), mismatched, float(turnover_diff))


def _table(frame: pd.DataFrame) -> str:
    """A pandas frame as a Markdown table (no extra dependency needed)."""
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def _dates(days: list[date]) -> str:
    return ", ".join(d.isoformat() for d in days) if days else "none"


def build_report(cfg: DataConfig, today: date) -> str:
    end = cfg.end_date(today)
    logged = read_log(cfg)

    # The latest outcome for each date, for the format that is primary on that date.
    primary = {
        day: row["status"]
        for (day, fmt), row in logged.items()
        if cfg.start <= day <= end and fmt is primary_format(cfg, day)
    }
    stored = sorted(d for d in primary if processed_path(cfg, d).exists())
    errors = sorted(d for d, s in primary.items() if s == "error")
    not_stored = sorted(d for d, s in primary.items() if s == "ok" and d not in set(stored))
    no_session = sorted(d for d, s in primary.items() if s == "not_found")
    weekday_no_session = [d for d in no_session if d.weekday() < 5]
    weekend_sessions = [d for d in stored if d.weekday() >= 5]

    out: list[str] = [
        "# Data-quality report: NSE F&O bhavcopy (index options)",
        "",
        f"Generated {today.isoformat()} for {', '.join(cfg.underlyings)}, "
        f"window {cfg.start.isoformat()} to {end.isoformat()}.",
        f"Primary format: legacy up to {cfg.legacy_last_date.isoformat()}, UDiFF after.",
        "",
        "## Coverage",
        "",
        f"- Calendar dates checked: {len(primary)} of {(end - cfg.start).days + 1}",
        f"- Trading days stored: **{len(stored)}**"
        + (f" ({stored[0].isoformat()} to {stored[-1].isoformat()})" if stored else ""),
        f"- Dates with no session (NSE returned 404): {len(no_session)}, of which "
        f"{len(weekday_no_session)} are weekdays",
        f"- Recent 404s that will be re-checked on the next download (may not be published "
        f"yet): {_dates([d for d in no_session if (today - d).days <= cfg.recheck_recent_days])}",
        f"- Download errors still unresolved: {len(errors)}: {_dates(errors)}",
        f"- Downloaded but not yet stored (run `build`): {_dates(not_stored)}",
        "",
        "## Weekend and holiday sessions (trap 6)",
        "",
        "Trading days stored that fall on a Saturday or Sunday (special sessions):",
        _dates(weekend_sessions),
        "",
        "## Weekdays with no session",
        "",
        "Most of these should be exchange holidays. M1 can't tell a holiday from a missing file,",
        "so M2 checks each date against NSE's official holiday list.",
        "",
    ]
    by_year: dict[int, list[date]] = {}
    for d in weekday_no_session:
        by_year.setdefault(d.year, []).append(d)
    for year, days in sorted(by_year.items()):
        out.append(f"- {year} ({len(days)}): {_dates(days)}")

    if not stored:
        out += ["", "No stored data yet; run `download` then `build`."]
        return "\n".join(out) + "\n"

    with connect(cfg) as con:
        rows_per_day = con.execute(
            """
            WITH d AS (SELECT trade_date, count(*) AS n FROM options GROUP BY trade_date)
            SELECT year(trade_date) AS year, count(*) AS days, min(n) AS min_rows,
                   CAST(median(n) AS INTEGER) AS median_rows, max(n) AS max_rows
            FROM d GROUP BY year ORDER BY year
            """
        ).df()
        thin_days = con.execute(
            """
            WITH d AS (SELECT trade_date, count(*) AS n FROM options GROUP BY trade_date),
                 y AS (SELECT year(trade_date) AS year, median(n) AS med FROM d GROUP BY year)
            SELECT trade_date, n FROM d JOIN y ON year(d.trade_date) = y.year
            WHERE n < 0.5 * y.med ORDER BY trade_date
            """
        ).df()
        zero_volume = con.execute(
            """
            SELECT year(trade_date) AS year, count(*) AS rows,
                   count(*) FILTER (WHERE zero_volume) AS zero_volume_rows,
                   round(100.0 * count(*) FILTER (WHERE zero_volume) / count(*), 1) AS pct
            FROM options GROUP BY year ORDER BY year
            """
        ).df()
        # An expiry date printed in a file is not proof that the expiry happened: at the
        # Thursday -> Tuesday switch NSE re-dated far contracts, so their old Thursday dates
        # never arrived. An expiry counts only if its contracts were still trading ON that
        # date. The ones that never arrived are listed separately.
        expiries = con.execute(
            """
            WITH e AS (SELECT DISTINCT expiry FROM options WHERE trade_date = expiry)
            SELECT year(expiry) AS year,
                   count(*) FILTER (WHERE dayofweek(expiry) = 1) AS Mon,
                   count(*) FILTER (WHERE dayofweek(expiry) = 2) AS Tue,
                   count(*) FILTER (WHERE dayofweek(expiry) = 3) AS Wed,
                   count(*) FILTER (WHERE dayofweek(expiry) = 4) AS Thu,
                   count(*) FILTER (WHERE dayofweek(expiry) = 5) AS Fri,
                   count(*) AS total
            FROM e GROUP BY year ORDER BY year
            """
        ).df()
        never_arrived = con.execute(
            """
            SELECT expiry::VARCHAR AS stated_expiry, dayname(expiry) AS weekday,
                   max(trade_date)::VARCHAR AS last_seen
            FROM options
            WHERE expiry <= (SELECT max(trade_date) FROM options)
            GROUP BY expiry HAVING NOT bool_or(trade_date = expiry)
            ORDER BY expiry
            """
        ).df()
        # Lot size belongs to a contract ON a trade date: NSE has changed the lot size of
        # existing contracts mid-life. So periods are shown by trade date, for the contract
        # the strategy trades (the nearest expiry). "Gaps and islands": start a new period
        # whenever the lot changes and number periods with a running sum, so two separate
        # periods sharing a value are not merged.
        nearest_lots = con.execute(
            """
            WITH nearest AS (
                SELECT trade_date, min(expiry) AS expiry FROM options
                WHERE expiry >= trade_date GROUP BY trade_date
            ),
            lots AS (
                SELECT n.trade_date, any_value(o.lot_size) AS lot
                FROM nearest n JOIN options o USING (trade_date, expiry)
                WHERE o.lot_size IS NOT NULL GROUP BY n.trade_date
            ),
            changes AS (
                SELECT *, CASE WHEN lot = lag(lot) OVER (ORDER BY trade_date) THEN 0 ELSE 1 END
                          AS is_new_period
                FROM lots
            ),
            periods AS (
                SELECT *, sum(is_new_period) OVER (ORDER BY trade_date) AS period FROM changes
            )
            SELECT any_value(lot) AS nearest_expiry_lot,
                   min(trade_date)::VARCHAR AS from_trade_date,
                   max(trade_date)::VARCHAR AS to_trade_date, count(*) AS trading_days
            FROM periods GROUP BY period ORDER BY from_trade_date
            """
        ).df()
        lot_changes = con.execute(
            """
            WITH c AS (
                SELECT expiry, trade_date, lot_size,
                       lag(lot_size) OVER (PARTITION BY expiry, strike, option_type
                                           ORDER BY trade_date) AS previous
                FROM options WHERE lot_size IS NOT NULL
            )
            SELECT trade_date::VARCHAR AS first_day_new_lot, previous AS old_lot,
                   lot_size AS new_lot, count(DISTINCT expiry) AS existing_expiries_changed
            FROM c WHERE previous <> lot_size GROUP BY ALL ORDER BY 1
            """
        ).df()
        same_day_conflicts = con.execute(
            """
            SELECT count(*) FROM (
                SELECT trade_date, expiry FROM options WHERE lot_size IS NOT NULL
                GROUP BY ALL HAVING count(DISTINCT lot_size) > 1
            )
            """
        ).fetchone()
        # Turnover counts notional value, so for UDiFF rows with trades
        # turnover / (contracts x lot x (strike + price)) is ~1 only if `contracts` counts
        # contracts. A median far from 1 would mean NSE changed the unit.
        volume_units = con.execute(
            """
            SELECT year(trade_date) AS year, count(*) AS traded_rows,
                   round(median(turnover_rs / (contracts * lot_size * (strike + close))), 4)
                       AS median_ratio
            FROM options
            WHERE source_format = 'udiff' AND contracts > 0
            GROUP BY year ORDER BY year
            """
        ).df()

    out += [
        "",
        "## Rows per trading day",
        "",
        _table(rows_per_day),
        "",
        f"Days with fewer than half their year's median rows: "
        f"{', '.join(f'{r.trade_date} ({r.n})' for r in thin_days.itertuples()) or 'none'}",
        "",
        "## Zero-volume rows (trap 4)",
        "",
        "Rows with no trades: their close is carried forward from an earlier day, so it is",
        "stale. They stay in the data, flagged as `zero_volume`, and are never used as fills.",
        "",
        _table(zero_volume),
        "",
        "## Expiry dates by weekday (trap 1)",
        "",
        "Expiries that actually happened: contracts were still trading on that date. The",
        "weekday pattern comes from the data, not from a rule: Thursday before the 1 Sep 2025",
        "switch, Tuesday after it, and other weekdays where a holiday moved an expiry.",
        "",
        _table(expiries),
        "",
        "Stated expiry dates that never arrived: the contracts stopped appearing under that",
        "date before it came, because NSE re-dated them, either to dodge a holiday or at the",
        "Thursday -> Tuesday switch. `last_seen` is the last day the old date was printed.",
        "",
        _table(never_arrived) if not never_arrived.empty else "none",
        "",
        "## Lot sizes (trap 2)",
        "",
        "From UDiFF's lot-size column, which only starts with the stored UDiFF data. Legacy",
        "files have no lot size; the sourced legacy table arrives in M2.",
        "",
        "Lot size of the nearest-expiry contract, by trade date:",
        "",
        _table(nearest_lots) if not nearest_lots.empty else "No UDiFF data stored yet.",
        "",
        "Days on which NSE changed the lot size of contracts that were already trading:",
        "",
        _table(lot_changes) if not lot_changes.empty else "none",
        "",
        f"Contract-days with two different lot sizes on the same day (should be 0): "
        f"**{same_day_conflicts[0] if same_day_conflicts else 0}**",
        "",
        "## Format checks (trap 7)",
        "",
        "### UDiFF volume unit",
        "",
        "Median of turnover / (contracts x lot x (strike + close)); ~1.0 means `contracts`",
        "counts contracts.",
        "",
        _table(volume_units) if not volume_units.empty else "No UDiFF data stored yet.",
        "",
        "### Legacy vs UDiFF on days where both files exist",
        "",
    ]

    overlap_days = sorted(
        d
        for (d, fmt), row in logged.items()
        if fmt is Format.UDIFF
        and d <= cfg.legacy_last_date
        and row["status"] == "ok"
        and raw_path(cfg, Format.LEGACY, d).exists()
    )
    if overlap_days:
        results = [compare_formats(cfg, d) for d in overlap_days]
        clean = [
            r
            for r in results
            if not r.mismatched_columns and r.matched == r.legacy_rows == r.udiff_rows
        ]
        out += [
            f"- Days compared: {len(results)} ({overlap_days[0]} to {overlap_days[-1]})",
            f"- Days where every contract matched and every shared column agreed: **{len(clean)}**",
            f"- Largest turnover difference: Rs {max(r.max_turnover_diff_rs for r in results):,.0f}"
            f" (legacy precision is Rs {TURNOVER_TOLERANCE_RS:,.0f})",
        ]
        for r in results:
            if r not in clean:
                out.append(
                    f"- MISMATCH {r.day}: legacy {r.legacy_rows}, UDiFF {r.udiff_rows}, "
                    f"matched {r.matched}, columns {list(r.mismatched_columns)}"
                )
    else:
        out.append("No days with both formats downloaded.")
    return "\n".join(out) + "\n"


def write_report(cfg: DataConfig, today: date, reports_dir: Path = Path("reports")) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / "data_quality.md"
    path.write_text(build_report(cfg, today), encoding="utf-8")
    return path
