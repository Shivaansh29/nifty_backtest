"""Parse both NSE F&O bhavcopy formats into ONE normalised table of index options.

Column meanings were settled from real files, not guessed (spec §4, trap 7). On the 9 days
where both formats were downloaded (Jan and Jun 2024), every NIFTY option contract matched
1:1 between the formats, and:
  legacy CLOSE       == UDiFF ClsPric      (not LastPric, which matched only ~25% of rows)
  legacy SETTLE_PR   == UDiFF SttlmPric
  legacy CONTRACTS   == UDiFF TtlTradgVol  (both count contracts, not units)
  legacy OPEN_INT    == UDiFF OpnIntrst    (both count units)
  legacy VAL_INLAKH  == UDiFF TtlTrfVal / 1e5 (notional turnover in rupees, strike included),
                        except that legacy gives lakhs to 2 decimals, i.e. only to the nearest
                        Rs 1,000; differences up to Rs 995 were seen and are precision, not meaning
  UDiFF XpryDt       == UDiFF FininstrmActlXpryDt on every row checked
The data-quality report re-checks these on every run (see quality.py).

One output row = one option contract on one trading day.
"""

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from nifty_backtest.marketdata.sources import Format

# The normalised schema, in column order. Columns a format doesn't provide are left empty
# (lot_size and underlying_price only exist in UDiFF files).
COLUMNS = [
    "trade_date",
    "underlying",
    "expiry",
    "strike",
    "option_type",
    "open",
    "high",
    "low",
    "close",
    "settle_price",
    "contracts",
    "turnover_rs",
    "open_interest",
    "change_in_oi",
    "lot_size",
    "underlying_price",
    "zero_volume",
    "source_format",
]

# Legacy dates look like "27-Jun-2024" or "03-JUN-2024". They are parsed with this table
# instead of strptime("%b"), whose month names depend on the computer's language setting.
_MONTH_NUMBER = {
    m: i
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1
    )
}

_LEGACY_COLUMNS = {
    "INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH", "LOW",
    "CLOSE", "SETTLE_PR", "CONTRACTS", "VAL_INLAKH", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP",
}  # fmt: skip
_UDIFF_COLUMNS = {
    "TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "FininstrmActlXpryDt", "StrkPric", "OptnTp",
    "OpnPric", "HghPric", "LwPric", "ClsPric", "SttlmPric", "UndrlygPric", "OpnIntrst",
    "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "NewBrdLotQty",
}  # fmt: skip


class BhavcopyError(ValueError):
    """A file doesn't look the way this parser expects. Stop and investigate; never guess."""


def legacy_date(text: str) -> date:
    """Parse '27-Jun-2024' / '03-JUN-2024'."""
    day, month, year = text.strip().split("-")
    return date(int(year), _MONTH_NUMBER[month.upper()], int(day))


def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) != 1:
            raise BhavcopyError(f"{path.name}: expected 1 file inside the zip, found {members}")
        raw = archive.read(members[0])
    # Read everything as text first; each column is converted explicitly below.
    return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)


def _require(frame: pd.DataFrame, needed: set[str], path: Path) -> None:
    missing = needed - set(frame.columns)
    if missing:
        raise BhavcopyError(
            f"{path.name}: missing columns {sorted(missing)}; has NSE changed the format?"
        )


def _num(column: pd.Series) -> pd.Series:
    return pd.to_numeric(column.str.strip())


def _parse_legacy(frame: pd.DataFrame, underlyings: tuple[str, ...]) -> pd.DataFrame:
    rows = frame[
        (frame["INSTRUMENT"].str.strip() == "OPTIDX")
        & frame["SYMBOL"].str.strip().isin(underlyings)
    ]
    return pd.DataFrame(
        {
            "trade_date": rows["TIMESTAMP"].map(legacy_date),
            "underlying": rows["SYMBOL"].str.strip(),
            "expiry": rows["EXPIRY_DT"].map(legacy_date),
            "strike": _num(rows["STRIKE_PR"]).astype("float64"),
            "option_type": rows["OPTION_TYP"].str.strip(),
            "open": _num(rows["OPEN"]).astype("float64"),
            "high": _num(rows["HIGH"]).astype("float64"),
            "low": _num(rows["LOW"]).astype("float64"),
            "close": _num(rows["CLOSE"]).astype("float64"),
            "settle_price": _num(rows["SETTLE_PR"]).astype("float64"),
            "contracts": _num(rows["CONTRACTS"]).astype("int64"),
            # VAL_INLAKH is in lakhs of rupees (1 lakh = 100,000).
            "turnover_rs": (_num(rows["VAL_INLAKH"]) * 100_000).round(2).astype("float64"),
            "open_interest": _num(rows["OPEN_INT"]).astype("int64"),
            "change_in_oi": _num(rows["CHG_IN_OI"]).astype("int64"),
            # Legacy files have no lot size; it comes from a sourced table in M2.
            "lot_size": pd.array([pd.NA] * len(rows), dtype="Int64"),
            "underlying_price": float("nan"),
        }
    )


def _parse_udiff(frame: pd.DataFrame, underlyings: tuple[str, ...], path: Path) -> pd.DataFrame:
    rows = frame[
        (frame["FinInstrmTp"].str.strip() == "IDO")  # IDO = index option
        & frame["TckrSymb"].str.strip().isin(underlyings)
    ]
    # The two expiry columns have always been equal. If they ever differ, which one is right
    # is a question the data must answer, so stop instead of picking one (trap 7).
    differ = rows["XpryDt"] != rows["FininstrmActlXpryDt"]
    if differ.any():
        raise BhavcopyError(
            f"{path.name}: {int(differ.sum())} rows where XpryDt != FininstrmActlXpryDt; "
            "decide which expiry is correct before normalising"
        )
    return pd.DataFrame(
        {
            "trade_date": rows["TradDt"].map(date.fromisoformat),
            "underlying": rows["TckrSymb"].str.strip(),
            "expiry": rows["XpryDt"].map(date.fromisoformat),
            "strike": _num(rows["StrkPric"]).astype("float64"),
            "option_type": rows["OptnTp"].str.strip(),
            "open": _num(rows["OpnPric"]).astype("float64"),
            "high": _num(rows["HghPric"]).astype("float64"),
            "low": _num(rows["LwPric"]).astype("float64"),
            "close": _num(rows["ClsPric"]).astype("float64"),
            "settle_price": _num(rows["SttlmPric"]).astype("float64"),
            "contracts": _num(rows["TtlTradgVol"]).astype("int64"),
            "turnover_rs": _num(rows["TtlTrfVal"]).astype("float64"),
            "open_interest": _num(rows["OpnIntrst"]).astype("int64"),
            "change_in_oi": _num(rows["ChngInOpnIntrst"]).astype("int64"),
            "lot_size": _num(rows["NewBrdLotQty"]).astype("Int64"),
            "underlying_price": _num(rows["UndrlygPric"]).astype("float64"),
        }
    )


def parse(
    path: Path, fmt: Format, expected_date: date, underlyings: tuple[str, ...]
) -> pd.DataFrame:
    """Read one bhavcopy zip and return its index-option rows in the normalised schema."""
    frame = _read_zip_csv(path)
    if fmt is Format.LEGACY:
        # Legacy lines end with a comma, which pandas reads as an extra, empty, unnamed column.
        frame = frame.loc[:, ~frame.columns.str.startswith("Unnamed")]
        _require(frame, _LEGACY_COLUMNS, path)
        out = _parse_legacy(frame, underlyings)
    else:
        _require(frame, _UDIFF_COLUMNS, path)
        out = _parse_udiff(frame, underlyings, path)

    if out.empty:
        raise BhavcopyError(f"{path.name}: no index-option rows for {underlyings}")
    dates_in_file = set(out["trade_date"])
    if dates_in_file != {expected_date}:
        raise BhavcopyError(
            f"{path.name}: trade dates {sorted(dates_in_file)}, expected {expected_date}"
        )
    if not set(out["option_type"]) <= {"CE", "PE"}:
        raise BhavcopyError(f"{path.name}: unexpected option types {set(out['option_type'])}")
    key = ["underlying", "expiry", "strike", "option_type"]
    if out.duplicated(key).any():
        raise BhavcopyError(f"{path.name}: duplicate contracts")

    # Trap 4: with no trades, NSE carries the previous close forward. Flag it so a stale
    # price is never mistaken for a real fill.
    out["zero_volume"] = out["contracts"] == 0
    out["source_format"] = fmt.value
    return out.sort_values(key).reset_index(drop=True)[COLUMNS]
