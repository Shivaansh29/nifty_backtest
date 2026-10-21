# NIFTY Options Backtester

[![CI](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml/badge.svg)](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml)

Backtests NIFTY 50 index option strategies on real NSE end-of-day data and shows the results in
an interactive web dashboard. Version 1 tests one strategy, a weekly short straddle, from
October 2021 to the latest trading day.

> **Status: M4 (metrics) complete.** The short straddle runs over five years of NSE data
> (263 weekly trades) with a dated, sourced cost model, and every spec metric is computed
> against a NIFTY 50 TRI buy-and-hold benchmark. All numbers below come from one saved,
> reproducible run.

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
uv run nifty-backtest backtest         # short straddle -> runs/<run_id>/ (trades, marks, equity, metrics)
uv run nifty-backtest metrics runs/<run_id>   # recompute metrics for a saved run
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
| M3 | Engine, short straddle, full cost model, per-trade context | done |
| M4 | Metrics and reports | done |
| M5 | FastAPI backend | planned |
| M6 | React dashboard | planned |
| M7 | Conditions and robustness, one at a time, out-of-sample | planned |
| M8 | Docker, polish, screenshots | planned |

## Results (v1 baseline: short straddle, hold to expiry)

From run `20261021-235646-short_straddle`:
- **Code:** commit `e0d32d4`, clean tree.
- **Data:** 1 Oct 2021 to 16 Oct 2026, 1,251 trading days.
- **Settings:** ₹5,00,000 capital, 1 lot, entry 3 sessions before expiry, brokerage ₹20/order, slippage 0.5 point per leg.

| | Strategy, net | Strategy, gross (no costs) | NIFTY 50 TRI buy-and-hold |
|---|---|---|---|
| Total P&L | ₹2,79,138.52 | ₹3,10,983.25 | ₹2,00,456.57 |
| ROI on ₹5L capital | 55.83% | 62.20% | 40.09% |
| CAGR | 9.20% | 10.07% | 6.92% |
| Max drawdown | ₹1,12,676.73 (22.26%) | ₹1,09,132.50 (21.55%) | ₹1,19,590.42 (16.44%) |
| **Sharpe / Sortino, return on notional, 0% target (headline)** | **0.56 / 0.74** | 0.65 / 0.85 | n/a |
| Sharpe / Sortino, rupee returns, 6.5% risk-free | 0.26 / 0.35 | 0.33 / 0.43 | 0.10 / 0.14 |
| *Sensitivity:* notional Sharpe / Sortino at 6.5% | −0.38 / −0.49 | −0.29 / −0.37 | n/a |

**How to read this:**
- **Trades:** 263, with 58.9% winners. The average trade made +3.46% of the premium collected
  (t = 0.78) and +15.75 index points per unit (t = 1.37).
- **Not statistically significant:** neither average is distinguishable from zero at the usual
  95% level.
- **Losses outweigh wins in size:** the average loss (₹8,209) is larger than the average win
  (₹7,521), and the worst single trade lost ₹41,067.
- **Year by year:** 2023 lost money while the index rose 21%.
- **Returns are on capital, not margin:** they're on the full ₹5,00,000, so return on the
  margin actually used would be higher.

Full methodology, per-year table and limitations: [`docs/milestones/M4.md`](docs/milestones/M4.md).

## How results are measured

- **P&L in three units.** NIFTY's lot size changed several times in this period
  (50 → 25 → 75 → 65 units), so "one lot" carried three times more exposure in 2025 than in
  mid-2024. Each trade therefore records P&L in rupees (at the actual lot size), in index
  points per unit, and as a % of the premium collected. Rupees drive the equity curve. Points
  and % are used to compare years and for Sharpe ratios and t-statistics, because they don't
  change when the lot size does.
- **Return on capital, not on margin.** Returns are measured on ₹5,00,000 starting capital. A
  one-lot short straddle only ties up part of that as margin, so the return on the margin
  actually used would be higher.
- **Benchmark.** NIFTY 50 Total Return Index (dividends reinvested), from NSE Indices: ₹5,00,000
  invested at the first day's close and held to the last, with no costs.
- **Risk-adjusted returns.** These are computed on **daily mark-to-market** data, annualised with
  252 days.
  - **Headline Sharpe and Sortino:** daily return on notional, i.e. the change in net P&L per
    unit divided by the NIFTY level at entry. They use a **0%** target, because a short
    straddle never invests its notional.
  - **Rupee and benchmark versions:** they use a **6.5%** risk-free rate.
  - **Gaps:** any missing day makes these ratios null. They are never stitched across a gap.
- **t-statistics.** Computed on net % of premium collected (leading) and net points per unit,
  never on rupees.
- **Costs.** Statutory and exchange charges come from a dated table in
  [`reference/cost_rates.csv`](reference/cost_rates.csv), every row citing an NSE circular,
  SEBI regulation, Finance Act or GST notification. That covers STT (changed on 1 Apr 2023,
  1 Oct 2024 and 1 Apr 2026), NSE transaction charges, IPFT, SEBI fees, stamp duty and GST.
  Brokerage (₹20 per order) and slippage (0.5 index points per leg) are assumptions: both are
  configurable, and every run records the values it used.

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
