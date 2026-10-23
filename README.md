# NIFTY Options Backtester

[![CI](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml/badge.svg)](https://github.com/Shivaansh29/nifty_backtest/actions/workflows/ci.yml)

Backtests NIFTY 50 index option strategies on real NSE end-of-day data and shows the results in
an interactive web dashboard. Version 1 tests one strategy, a weekly short straddle, from
October 2021 to the latest trading day.

> **Status: M6 (dashboard) complete.** The short straddle runs over five years of NSE data
> (263 weekly trades) with a dated, sourced cost model, and every spec metric is computed
> against a NIFTY 50 TRI buy-and-hold benchmark. All numbers below come from one saved,
> reproducible run. A FastAPI backend serves saved runs and launches new ones, and a React
> dashboard shows them.

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
uv run nifty-backtest serve            # REST API on http://127.0.0.1:8000 (docs at /docs)
```

Open the dashboard (two terminals; needs [Node](https://nodejs.org/) 24.14.1, see
`frontend/.nvmrc`):

```bash
uv run nifty-backtest serve                  # terminal 1: the API on 127.0.0.1:8000
cd frontend && npm ci && npm run dev         # terminal 2: then open http://127.0.0.1:5173
```

Run the same checks as CI:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
cd frontend && npm run typecheck && npm test && npm run build
```

## Roadmap

| # | Milestone | Status |
|---|---|---|
| M0 | Repo setup: uv, ruff, mypy, pytest, CI | done |
| M1 | Data ingestion: NSE bhavcopy (both formats) to Parquet + DuckDB, data-quality report | done |
| M2 | Reference data: expiry calendar, special sessions, lot sizes, index, TRI, VIX, settlement | done |
| M3 | Engine, short straddle, full cost model, per-trade context | done |
| M4 | Metrics and reports | done |
| M5 | FastAPI backend | done |
| M6 | React dashboard | done |
| M7 | Conditions and robustness, one at a time, out-of-sample | planned |
| M8 | Docker, polish, screenshots | planned |

## Results (v1 baseline: short straddle, hold to expiry)

From run `20261024-033815-short_straddle`:
- **Code:** commit `be47d67`, clean tree.
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
- **Missing data elsewhere.** ROI, total P&L and CAGR are null if the last day's equity is
  missing; an earlier day is never used instead. With missing days, max drawdown is reported as
  an observed lower bound. A monthly or yearly return is null if either of its boundary days is
  missing. `metrics.json` writes null, never NaN.
- **t-statistics.** Computed on net % of premium collected (leading) and net points per unit,
  never on rupees.
- **Costs.** Statutory and exchange charges come from a dated table in
  [`reference/cost_rates.csv`](reference/cost_rates.csv), every row citing an NSE circular,
  SEBI regulation, Finance Act or GST notification. That covers STT (changed on 1 Apr 2023,
  1 Oct 2024 and 1 Apr 2026), NSE transaction charges, IPFT, SEBI fees, stamp duty and GST.
  Brokerage (₹20 per order) and slippage (0.5 index points per leg) are assumptions: both are
  configurable, and every run records the values it used.

## API

`uv run nifty-backtest serve` starts a FastAPI server on **127.0.0.1:8000**. Interactive
documentation, generated from the code, is at http://127.0.0.1:8000/docs.

| Method and path | Returns |
|---|---|
| `GET /api/health` | status and version |
| `GET /api/runs` | every saved run, newest first, with status (`complete`, `metrics_missing` or `invalid`, plus the reasons) and headline numbers |
| `GET /api/runs/{run_id}` | full config, manifest (git commit, data fingerprints) and which files the run holds |
| `GET /api/runs/{run_id}/metrics` | `metrics.json` as saved |
| `GET /api/runs/{run_id}/yearly`, `/monthly` | the calendar-year and monthly tables |
| `GET /api/runs/{run_id}/trades` | the trade log |
| `GET /api/runs/{run_id}/trades/{trade_id}` | one trade with its daily marks |
| `GET /api/runs/{run_id}/equity` | the daily equity curve |
| `GET /api/runs/{run_id}/skipped` | weeks not traded, with the reason |
| `GET /api/runs/{run_id}/daily` | daily net and gross equity, drawdowns and the NIFTY 50 TRI curve, for charts (M6) |
| `POST /api/runs` | run a backtest with parameters and save it, exactly like `nifty-backtest backtest` |

```bash
curl -s http://127.0.0.1:8000/api/runs
curl -s http://127.0.0.1:8000/api/runs/<run_id>/metrics
curl -s http://127.0.0.1:8000/api/runs/<run_id>/trades/NIFTY-2026-05-12
curl -s -X POST http://127.0.0.1:8000/api/runs -H 'content-type: application/json' \
     -d '{"start": "2025-01-01", "end": "2025-03-31", "slippage_points_per_leg": 1.0}'
```

How the API behaves:
- **It serves saved files exactly as written.** GET requests never recompute metrics; use
  `nifty-backtest metrics` to compute them for a run that has none.
- **Every file is checked before it is served.** A missing, unreadable or unexpectedly shaped
  file returns an error naming that file; nothing is served half-read.
- **Errors share one JSON shape,** `{error, detail, run_id, artifact}`:

  | Status | When |
  |---|---|
  | 404 | the run or trade doesn't exist |
  | 409 | metrics were never computed, or a launch conflicts with another |
  | 422 | invalid parameters or run id |
  | 500 | a saved file is broken, or a launched run failed |
  | 503 | there is no local market data to launch a run with |

- **It binds to localhost** because it has no authentication. `--host` can change that, and
  the command warns when it does.

## Dashboard

The dashboard (`frontend/`) is a React + TypeScript app that reads everything from the API.
- **Run list:** every saved run with its status and headline numbers.
- **Run page:**
  - headline ROI, CAGR, drawdown, Sharpe/Sortino and trade statistics;
  - the net / gross / NIFTY 50 TRI comparison;
  - equity and drawdown charts against the TRI;
  - calendar-year table and monthly heatmap;
  - a sortable, searchable trade table.
- **Trade page:** one trade's facts, costs and daily marks.
- **New run:** a form that launches a backtest through `POST /api/runs`.

It does no financial calculation: every number is the API's, and the browser only formats,
sorts and lays it out. Its TypeScript types are generated from the API's OpenAPI schema
(`uv run nifty-backtest openapi`, then `npm run gen:types`), and CI fails if either copy is
out of date. In development, Vite forwards `/api` to the API server, so no CORS setup is
needed.

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
  api/                  FastAPI backend: reads and checks run folders, launches runs (M5)
tests/                  pytest suite
reference/              hand-maintained, sourced reference files (tracked)
frontend/               React + TypeScript dashboard: Vite, Tailwind, Recharts, TanStack Table (M6)
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
