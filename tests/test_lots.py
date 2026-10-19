"""Where each row's lot size comes from (trap 2), on synthetic data."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from nifty_backtest.marketdata.bhavcopy import parse
from nifty_backtest.marketdata.config import DataConfig
from nifty_backtest.marketdata.lots import fill_lot_sizes, legacy_table, lot_from_table
from nifty_backtest.marketdata.sources import Format
from tests.helpers import FIXTURE_DAY, install_fixture

REAL_TABLE = Path(__file__).resolve().parents[1] / "reference" / "lot_sizes_legacy.csv"


def write_table(directory: Path, rows: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    header = "underlying,from_trade_date,to_trade_date,lot_size,source,source_url,note"
    (directory / "lot_sizes_legacy.csv").write_text("\n".join([header, *rows]) + "\n")


def test_committed_table_covers_the_pre_udiff_years_with_lot_50() -> None:
    # Hand check against NSE/FAOP/47854: every NIFTY contract has lot 50 after 25 Jun 2021.
    table = legacy_table(REAL_TABLE)
    assert lot_from_table(table, "NIFTY", date(2021, 10, 1)) == 50
    assert lot_from_table(table, "NIFTY", date(2023, 12, 29)) == 50
    # From 2024 the lot comes from UDiFF rows, not the table.
    assert lot_from_table(table, "NIFTY", date(2024, 1, 1)) is None
    assert lot_from_table(table, "BANKNIFTY", date(2022, 1, 3)) is None


def test_overlapping_table_rows_are_rejected(tmp_path: Path) -> None:
    write_table(
        tmp_path, ["NIFTY,2022-01-01,2022-12-31,50,src,u,", "NIFTY,2022-06-01,2023-01-31,25,src,u,"]
    )
    with pytest.raises(ValueError, match="overlapping"):
        lot_from_table(legacy_table(tmp_path / "lot_sizes_legacy.csv"), "NIFTY", date(2022, 7, 1))


def test_table_rows_need_a_source(tmp_path: Path) -> None:
    write_table(tmp_path, ["NIFTY,2022-01-01,2022-12-31,50,,u,"])
    with pytest.raises(ValueError, match="source"):
        legacy_table(tmp_path / "lot_sizes_legacy.csv")


def legacy_rows(cfg: DataConfig) -> object:
    return parse(install_fixture(cfg, Format.LEGACY), Format.LEGACY, FIXTURE_DAY, ("NIFTY",))


def test_legacy_day_with_same_day_udiff_file_takes_its_lot_sizes(cfg: DataConfig) -> None:
    install_fixture(cfg, Format.UDIFF)
    frame = fill_lot_sizes(legacy_rows(cfg), cfg, FIXTURE_DAY)  # type: ignore[arg-type]
    assert set(frame["lot_size"]) == {50}  # NewBrdLotQty in the synthetic UDiFF file
    assert set(frame["lot_size_source"]) == {"udiff_same_day"}


def test_legacy_day_without_udiff_uses_the_table(cfg: DataConfig, tmp_path: Path) -> None:
    write_table(tmp_path / "ref", ["NIFTY,2024-01-01,2024-03-31,40,test source,u,"])
    cfg = replace(cfg, reference_dir=tmp_path / "ref")
    frame = fill_lot_sizes(legacy_rows(cfg), cfg, FIXTURE_DAY)  # type: ignore[arg-type]
    assert set(frame["lot_size"]) == {40}
    assert set(frame["lot_size_source"]) == {"reference_table"}


def test_no_source_leaves_lot_size_empty(cfg: DataConfig, tmp_path: Path) -> None:
    write_table(tmp_path / "ref", ["NIFTY,2022-01-01,2022-12-31,50,test source,u,"])
    cfg = replace(cfg, reference_dir=tmp_path / "ref")
    frame = fill_lot_sizes(legacy_rows(cfg), cfg, FIXTURE_DAY)  # type: ignore[arg-type]
    assert frame["lot_size"].isna().all()  # M3 skips such weeks instead of guessing
    assert frame["lot_size_source"].isna().all()


def test_udiff_rows_keep_their_own_lot_size(cfg: DataConfig) -> None:
    udiff = parse(install_fixture(cfg, Format.UDIFF), Format.UDIFF, FIXTURE_DAY, ("NIFTY",))
    frame = fill_lot_sizes(udiff, cfg, FIXTURE_DAY)
    assert set(frame["lot_size_source"]) == {"udiff"}
