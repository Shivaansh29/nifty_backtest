"""Command-line interface, run as `uv run nifty-backtest <command> ...`.

Each milestone adds subcommands here. The CLI only parses arguments and calls into the
modules that do the work, so all logic stays testable without going through the command line.
"""

import argparse
import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import date

from nifty_backtest import __version__
from nifty_backtest.marketdata.config import DataConfig


def _download(args: argparse.Namespace, cfg: DataConfig) -> int:
    from nifty_backtest.marketdata.download import download_range, make_client

    with make_client(cfg) as client:
        summary = download_range(cfg, client, today=date.today())
    print(
        f"downloaded {summary.downloaded}, no file (404) {summary.not_found}, "
        f"errors {summary.errors}, already done {summary.skipped}"
    )
    return 1 if summary.errors else 0


def _download_index(args: argparse.Namespace, cfg: DataConfig) -> int:
    from nifty_backtest.marketdata.download import make_client
    from nifty_backtest.marketdata.holidays import download_holidays
    from nifty_backtest.marketdata.indices import download_indices

    with make_client(cfg) as client:
        summary = download_indices(cfg, client, today=date.today())
        holidays = download_holidays(cfg, client, today=date.today())
    print(
        f"index months fetched {summary.fetched} (already cached {summary.cached}); "
        f"days filled from the NSE archive {summary.archive_days}; "
        f"holiday lists fetched {holidays}"
    )
    return 0


def _build(args: argparse.Namespace, cfg: DataConfig) -> int:
    from nifty_backtest.marketdata.indices import build_indices, index_path
    from nifty_backtest.marketdata.store import build

    written, current = build(cfg, today=date.today(), rebuild=args.rebuild)
    print(f"stored {written} trading days ({current} already up to date) in {cfg.processed_dir}")
    try:
        index = build_indices(cfg, today=date.today())
        print(f"stored {len(index)} days of NIFTY 50 / India VIX / TRI in {index_path(cfg)}")
    except FileNotFoundError as exc:
        print(f"index data skipped: {exc}")
    return 0


def _expiries(args: argparse.Namespace, cfg: DataConfig) -> int:
    from pathlib import Path

    from nifty_backtest.marketdata.store import connect
    from nifty_backtest.marketdata.trading_calendar import expiry_calendar

    with connect(cfg) as con:
        calendar = expiry_calendar(con, cfg, entry_days_before=args.entry_days_before)
    out = Path("reports") / "expiry_calendar.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    calendar.to_csv(out, index=False)
    print(calendar["status"].value_counts().to_string())
    print(f"expiry calendar written to {out}")
    return 0


def _report(args: argparse.Namespace, cfg: DataConfig) -> int:
    from nifty_backtest.marketdata.quality import write_report

    path = write_report(cfg, today=date.today())
    print(f"data-quality report written to {path}")
    return 0


def _sql(args: argparse.Namespace, cfg: DataConfig) -> int:
    from nifty_backtest.marketdata.store import query

    print(query(cfg, args.statement).to_string(index=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 = success).

    `argv` defaults to the real command-line arguments; tests pass a list instead.
    """
    parser = argparse.ArgumentParser(
        prog="nifty-backtest",
        description="Backtest NIFTY index option strategies on NSE end-of-day data.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")

    download = commands.add_parser("download", help="download NSE F&O bhavcopies into data/raw")
    download.add_argument("--start", type=date.fromisoformat, help="first date, YYYY-MM-DD")
    download.add_argument("--end", type=date.fromisoformat, help="last date, YYYY-MM-DD")
    commands.add_parser(
        "download-index", help="download NIFTY 50 OHLC, India VIX, NIFTY 50 TRI and NSE holidays"
    )
    build = commands.add_parser(
        "build", help="normalise downloaded files into Parquet (data/processed)"
    )
    build.add_argument(
        "--rebuild",
        action="store_true",
        help="re-parse every day (after rules or reference files change)",
    )
    expiries = commands.add_parser("expiries", help="write the expiry calendar to reports/")
    expiries.add_argument(
        "--entry-days-before",
        type=int,
        default=3,
        help="full trading days before expiry (default 3)",
    )
    commands.add_parser("report", help="write the data-quality report to reports/")
    sql = commands.add_parser("sql", help="run a DuckDB SQL query against the `options` view")
    sql.add_argument("statement", help='e.g. "SELECT count(*) FROM options"')

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # our own log already names each file
    cfg = DataConfig()
    if getattr(args, "start", None) is not None:
        cfg = replace(cfg, start=args.start)
    if getattr(args, "end", None) is not None:
        cfg = replace(cfg, end=args.end)

    handlers = {
        "download": _download,
        "download-index": _download_index,
        "build": _build,
        "expiries": _expiries,
        "report": _report,
        "sql": _sql,
    }
    return handlers[args.command](args, cfg)
