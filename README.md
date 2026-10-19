# NIFTY Options Backtester

[![CI](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml/badge.svg)](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml)

Backtests NIFTY 50 index option strategies on real NSE end-of-day data and shows the results in
an interactive web dashboard. Version 1 tests one strategy, a weekly short straddle, from
October 2021 to the latest trading day.

> **Status: M2 (reference data) complete.** Five years of NSE F&O bhavcopies are downloaded,
> normalised and queryable, with a verified expiry calendar, lot sizes, special sessions,
> NIFTY 50 / India VIX / TRI and expiry settlement levels. There are no backtest results yet: every number that appears here
> later will come from a saved, reproducible run.

## Principles

- Every number traces back to a raw NSE file. Nothing is estimated, invented or silently filled.
- Known data traps are handled explicitly and tested: moving expiry weekdays, changing lot sizes,
  the expiry-day settle column, stale prices, holidays and special sessions.
- Built milestone by milestone. Each one ends with tests, a demo command and plain-language
  notes in [`docs/milestones/`](docs/milestones/).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/). uv installs the pinned Python version (3.12) itself.

```bash
uv sync                          # create .venv with the exact versions in uv.lock
uv run nifty-backtest --version  # the command-line tool
```

Get the data (runs on your machine only; about 1.5 GB and roughly 1.5 hours the first time,
because requests to NSE are spaced out politely; re-runs only fetch what is missing):

```bash
uv run nifty-backtest download         # NSE F&O files -> data/raw (resumable)
uv run nifty-backtest download-index   # NIFTY 50, India VIX, NIFTY 50 TRI, NSE holiday lists
uv run nifty-backtest build            # normalise -> data/processed (Parquet)
uv run nifty-backtest expiries         # expiry calendar -> reports/expiry_calendar.csv
uv run nifty-backtest report           # data-quality report -> reports/data_quality.md
uv run nifty-backtest sql "SELECT count(*) FROM options"   # query with DuckDB
```

Run the same checks as CI:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

## Roadmap

| # | Milestone | Status |
|---|---|---|
| M0 | Repo setup: uv, ruff, mypy, pytest, CI | done |
| M1 | Data ingestion: NSE bhavcopy (both formats) to Parquet + DuckDB, data-quality report | done |
| M2 | Reference data: expiry calendar, special sessions, lot sizes, index, TRI, VIX, settlement | done |
| M3 | Engine, short straddle, full cost model, per-trade context | planned |
| M4 | Metrics and reports | planned |
| M5 | FastAPI backend | planned |
| M6 | React dashboard | planned |
| M7 | Conditions and robustness, one at a time, out-of-sample | planned |
| M8 | Docker, polish, screenshots | planned |

## How results will be measured

- **P&L in three units.** NIFTY's lot size changed several times in this period
  (50 → 25 → 75 → 65 units), so "one lot" carried three times more exposure in 2025 than in
  mid-2024. Each trade therefore records P&L in rupees (at the actual lot size), in index
  points per unit, and as a % of the premium collected. Rupees drive the equity curve. Points
  and % are used to compare years and for Sharpe ratios and t-statistics, because they don't
  change when the lot size does.
- **Return on capital, not on margin.** Returns are measured on ₹5,00,000 starting capital. A
  one-lot short straddle only ties up part of that as margin, so the return on the margin
  actually used would be higher.
- **Benchmark.** NIFTY 50 Total Return Index (dividends reinvested), from NSE.
- **Costs.** Brokerage, STT, exchange charges, GST, stamp duty, SEBI fees and slippage. Statutory
  rates come from a dated table that cites NSE/SEBI circulars and the Finance Act.

## Data

Free NSE end-of-day files, downloaded into `data/` on your own machine. That folder is never
committed, because NSE data is not redistributed here. CI tests use small synthetic files with
NSE's real column layout; tests on real data run locally and are skipped when the data is absent.

## Project layout

```
src/nifty_backtest/     Python package: cli.py plus one sub-package per module
  marketdata/           NSE downloads, normalisation, Parquet/DuckDB, calendar, lot sizes (M1-M2)
  strategies/           strategy interface and the short straddle (M3)
  engine/               positions, daily marks, expiry settlement, trade log (M3)
  costs/                brokerage, taxes, exchange fees, slippage (M3)
  metrics/              P&L, drawdown, Sharpe/Sortino, t-statistics, benchmark (M4)
  api/                  FastAPI backend (M5)
tests/                  pytest suite
reference/              hand-maintained, sourced reference files (tracked)
config/                 run configuration: strategy parameters, brokerage, slippage (M3)
frontend/               React + TypeScript dashboard (M6)
docs/milestones/        notes for each milestone
data/ runs/ reports/    downloaded data, saved runs, generated reports (not in git)
```

## Tech stack

Python 3.12 · uv · pandas · numpy · Parquet + DuckDB · FastAPI + Pydantic · React + TypeScript +
Vite · Tailwind CSS · Recharts · TanStack Table · pytest · Vitest · ruff · mypy · GitHub Actions ·
Docker

The full project spec is in [`CLAUDE.md`](CLAUDE.md).

## License

Code: [MIT](LICENSE). NSE data is not included and is not covered by this license.
