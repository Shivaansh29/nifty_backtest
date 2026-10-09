"""Command-line interface, run as `uv run nifty-backtest ...`.

M0 only wires up the entry point and `--version`. Later milestones add subcommands here,
for example downloading NSE data (M1) and running a backtest (M3).
"""

import argparse
from collections.abc import Sequence

from nifty_backtest import __version__


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code (0 = success).

    `argv` defaults to the real command-line arguments; tests pass a list instead.
    """
    parser = argparse.ArgumentParser(
        prog="nifty-backtest",
        description="Backtest NIFTY index option strategies on NSE end-of-day data.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)

    # There are no subcommands yet (they arrive from M1), so show what the tool is.
    parser.print_help()
    return 0
