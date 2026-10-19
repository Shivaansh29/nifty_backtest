"""Expiry settlement (spec §4, trap 3).

On expiry day NSE puts the index's FINAL SETTLEMENT LEVEL in the settle-price column of the
expiring options, not the options' own prices. So an option's value at expiry is its intrinsic
value, computed from that level. Every expiring contract must show the same level; if they
disagree, something is wrong and we stop instead of picking one.
"""

import duckdb


class SettlementError(ValueError):
    pass


def intrinsic_value(option_type: str, strike: float, level: float) -> float:
    """Value of one option unit at expiry: max(level - strike, 0) for a call,
    max(strike - level, 0) for a put."""
    if option_type == "CE":
        return max(level - strike, 0.0)
    if option_type == "PE":
        return max(strike - level, 0.0)
    raise ValueError(f"unknown option type {option_type!r}")


def settlement_level(
    con: duckdb.DuckDBPyConnection, expiry: str | object, underlying: str = "NIFTY"
) -> float:
    """The final settlement level for one real expiry, read from its expiring contracts."""
    values = con.execute(
        """
        SELECT DISTINCT settle_price FROM options
        WHERE underlying = ? AND trade_date = ? AND expiry = ?
        """,
        [underlying, expiry, expiry],
    ).fetchall()
    if not values:
        raise SettlementError(f"{expiry}: no expiring {underlying} contracts traded that day")
    if len(values) > 1:
        found = sorted(v[0] for v in values)[:5]
        raise SettlementError(f"{expiry}: expiring contracts disagree on settle price {found}...")
    return float(values[0][0])
