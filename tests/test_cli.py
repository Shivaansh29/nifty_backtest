"""M0 placeholder tests: the package installs, reports its version, and its CLI runs.

Real tests arrive with real code from M1 onwards.
"""

import tomllib
from pathlib import Path

import pytest

from nifty_backtest import __version__
from nifty_backtest.cli import main

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_comes_from_pyproject() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert __version__ == declared


def test_cli_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    # argparse's "version" action prints the version and then exits with status 0.
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"nifty-backtest {__version__}"


def test_cli_without_arguments_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: nifty-backtest" in capsys.readouterr().out
