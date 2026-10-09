# NIFTY Options Backtester — Project Spec

> Single source of truth for this project. Read it at the start of every session.
> Owner: Shivaansh Aggarwal. Built milestone by milestone, with owner review after each one.

## 1. Purpose

A portfolio / GitHub / CV project that backtests NIFTY index option strategies on real NSE data
and shows the results in an interactive web dashboard. It must:

- use a realistic, industry-relevant tech stack the owner can reuse in future work
- be correct and honest: every number traceable to raw data, nothing estimated or invented
- be clear enough that the owner can explain every module in an interview
- start simple (one strategy, one index) but be structured so new strategies and indices
  (e.g. BANKNIFTY) can be added later without rewrites

## 2. Scope of v1

| Item | v1 decision |
|---|---|
| Underlying | NIFTY 50 index options only |
| Period | Last 5 years: 1 Oct 2021 to the latest available trading day |
| Expiries | Nearest weekly expiry |
| Strategy | Short straddle (rules in §5) |
| Capital | ₹5,00,000 starting, 1 lot per trade, no compounding in v1 |
| Data | Free NSE end-of-day data (§4) |
| Interface | CLI first, then FastAPI backend + React dashboard |

Out of scope for v1 (planned later): other strategies, BANKNIFTY/SENSEX, intraday data,
SPAN margin model, position scaling/compounding, taxes.

## 3. Tech stack

| Layer | Choice | Why it's worth learning |
|---|---|---|
| Language | Python 3.12+ | Standard for quant and data work |
| Env & deps | `uv` | Modern Python project management |
| Data processing | pandas, numpy | Industry standard in finance |
| Storage | Parquet files + DuckDB (SQL over Parquet) | Columnar storage and analytical SQL, common in data engineering |
| Backend API | FastAPI + Pydantic | Typed REST APIs with auto-generated docs |
| Frontend | React + TypeScript + Vite | Production-grade frontend stack |
| Styling | Tailwind CSS | Widely used utility-first styling |
| Charts | Recharts (TradingView Lightweight Charts where useful) | Interactive financial charts |
| Tables | TanStack Table | Sortable / filterable trade logs |
| Testing | pytest (backend), Vitest (frontend) | Automated correctness checks |
| Quality | ruff (lint/format), mypy (types) | Clean, typed code |
| CI | GitHub Actions | Lint + tests on every push |
| Packaging | Docker + docker-compose (final milestone) | One-command run anywhere |

Also approved by the owner: `pyarrow` (Parquet engine for pandas), `httpx` (downloads) and
`pandas-stubs` (dev only, so mypy can check pandas code). `yfinance` may be used only to fill
specific gaps in index/VIX data, and only after asking.

Do not add frameworks or major dependencies beyond this list without asking the owner first.

## 4. Data

**Source:** NSE F&O bhavcopy (daily end-of-day files).

- Legacy format: up to 5 Jul 2024, the last legacy file (no lot-size column)
- UDiFF format: primary source from 8 Jul 2024 (has a lot-size column). UDiFF files also exist
  from at least 2 Jan 2024, so the two formats overlap for about six months (see trap 7).
- Both are normalised into ONE internal schema.
- NIFTY 50 daily OHLC, NIFTY 50 TRI (for the benchmark) and India VIX: NSE archives
  (Yahoo Finance only as a gap-filler, see §3).
- Downloads are cached locally, resumable, rate-limited politely, and never committed to git
  (`data/` is fully gitignored).
- Hand-maintained reference files (legacy lot sizes, special sessions, cost rates, events) live
  in a top-level `reference/` folder, which IS tracked. Every row cites a primary source.

**Known traps — handle from day one, never hardcode:**

1. **Expiry dates:** derive from the contract rows. NIFTY weeklies moved Thursday → Tuesday
   from 1 Sep 2025, and holidays shift individual expiries (e.g. to Wednesday).
2. **Lot size:** changed several times in this window (50 → 25 → 75 → 65). It belongs to the
   contract (expiry), not the trade date: changes roll over expiry by expiry, so contracts trading
   on the same day can have different lot sizes. Read it per contract where the file provides it.
   For legacy files (Oct 2021 – Jul 2024, which includes the 2024 50 → 25 change) use a dated
   table in `reference/` with exact effective dates from the NSE circulars, cited per row.
   Cross-check the table against UDiFF data where they overlap.
3. **Expiry-day settle column:** on expiry day NSE puts the *index final settlement level* in the
   settle column of expiring options, not the option's own price. Option value at expiry =
   intrinsic value computed from that level.
4. **Zero-volume rows:** the close may be stale (carried forward). Flag them; never treat a stale
   price as a real fill without marking it.
5. **Holidays / missing days:** detect and log; never silently fill.
6. **Special sessions:** weekend and holiday sessions (e.g. Budget days, Muhurat trading) also
   have bhavcopies. A trading day is any day with a bhavcopy; the downloader tries every calendar
   date and logs a 404 as "no session". Short sessions (Muhurat) are flagged from
   `reference/special_sessions.csv` and never used as entry days.
7. **Format overlap:** use the legacy/UDiFF overlap to settle what UDiFF columns mean (close vs
   last price, its two expiry columns, volume units). If there is no genuine overlap to answer
   a question, stop and ask the owner. Never guess.

**Data quality report (required output of M1/M2):** trading days loaded, holidays skipped,
expiries by weekday per year, lot sizes by period, rows per day, zero-volume row counts, gaps.

## 5. Strategy v1 — Short Straddle (defaults, all configurable)

- **Instrument:** nearest weekly NIFTY expiry = the first expiry strictly after the entry date
  (monthly expiries included).
- **Entry:** sell 1 ATM call + 1 ATM put at the close, `entry_days_before_expiry` trading days
  before expiry (default 3). ATM = strike nearest to the index close (exact midpoint: the lower
  strike). If two expiries are closer together than that, the entry day can be the previous
  expiry day: the old position settles and the new one opens at the same close.
- **Skipped weeks:** skip a week, and log why, if either ATM leg is missing or has zero volume
  at entry, or the settlement level is missing.
- **Exit (v1 base):** hold to expiry; settle at intrinsic value from NSE's official settlement level.
- **Exit (later milestone):** optional stop-loss / take-profit checked against each leg's daily
  high/low (not just the close), with conservative fill assumptions documented.
- **Costs:** brokerage, STT, exchange charges, GST, stamp duty, SEBI fees, plus configurable
  slippage per leg. Statutory and exchange rates live in one dated rate table in `reference/`:
  each rate has an effective-from date and a primary source (NSE/SEBI circular or the Finance
  Act, never a news article) cited next to it. STT changed at least twice in the window
  (1 Oct 2024 and 1 Apr 2026). Brokerage and slippage are assumptions and live in run config.
- **Frequency:** every week with valid data (~250 trades over 5 years). No regime filters in v1 —
  the goal is a large, honest baseline sample.
- **Context logged with every trade (from M3, not used for decisions in v1):** India VIX at entry,
  NIFTY close at entry and at expiry settlement, % move over the trade, days to expiry at entry,
  and an event tag if a major scheduled event fell inside the trade window. Events come from a
  small hand-maintained CSV (`reference/events.csv`: date, type, description — Union Budget,
  RBI policy decisions, general election results) with sources noted. This lets later milestones
  slice results by regime without re-running the backtest.
- **Conditions are added later (M7), one at a time, each tested out-of-sample:** entry timing,
  VIX regime filter, event-week skip, stop-loss/take-profit, trend (ADX) filter. Never add several
  at once — the effect of each must be measurable on its own.
- **Reporting note:** v1 ROI is on ₹5,00,000 starting capital, and one lot's margin is only part
  of that capital, so the README must state that return on the margin actually used would be
  higher. Quote a margin figure only with a dated, citable source.

## 6. Metrics (every run)

**P&L in three units, per trade:** ₹ (actual lot size), index points per unit, and % of premium
collected. Lot size changed up to 3x within the window, so ₹ drives the equity curve while
points and % are used for cross-year comparisons, Sharpe and t-statistics. The README explains why.

Total P&L, ROI, CAGR, monthly returns, win rate, average win / average loss, best/worst trade,
max drawdown (₹ and %), Sharpe on returns in excess of a configurable risk-free rate
(default 6.5%), Sortino, t-statistic of mean trade P&L, per-year breakdown, and NIFTY 50 TRI
buy-and-hold over the same period for context.

Sharpe and Sortino use a daily mark-to-market series. Headline numbers use return on notional
(daily change in points per unit ÷ index level at entry); the ₹ version is shown alongside.

Every run is saved with: run id, full config, git commit, trade log, metrics, and a lightweight
data manifest (date range, trading-day count, hash of the stored data files).

## 7. Milestones

Each milestone ends with:
(a) a demo command the owner runs,
(b) passing tests,
(c) `docs/milestones/MX.md` — plain-language notes on what was built, key design decisions,
    and 3–5 "explain-back" questions the owner should be able to answer.

**Stop after each milestone and wait for owner approval before starting the next.**

| # | Milestone | Done when |
|---|---|---|
| M0 | Repo setup: `uv` project, folder structure, ruff/mypy/pytest, GitHub Actions CI, README skeleton, `.gitignore` | CI passes on a placeholder test |
| M1 | Data ingestion: download 5 years of bhavcopy (both formats), normalise, store as Parquet, query with DuckDB | Data quality report generated; normaliser tests pass (synthetic fixtures in CI, real cached files locally) |
| M2 | Reference data: expiry calendar, special sessions, lot sizes, index OHLC, TRI, VIX, settlement handling | Calendar and lot sizes verified against known dates; test for the settle-column trap |
| M3 | Engine + short straddle (hold to expiry) + full cost model incl. slippage + per-trade context logging (VIX, moves, event tags — §5) | Trade log produced with context columns; at least 2 trades verified by hand against raw files (local real-data tests); one test covering an event-week trade (e.g. 4 Jun 2024) |
| M4 | Metrics & reports: all §6 metrics incl. drawdown, per-year breakdown, benchmark, results with vs without costs; CLI summary | Metrics tested against a hand-computed example |
| M5 | FastAPI backend: list runs, get run details, launch a run with parameters | API tests pass; OpenAPI docs page works |
| M6 | React dashboard: run form, equity curve, drawdown chart, monthly returns heatmap, trade table, single-trade drill-down | Dashboard runs locally against the API |
| M7 | Conditions & robustness: add §5 conditions one at a time (entry timing, VIX filter, event skip, stop-loss/take-profit via daily high/low, ADX filter); in-sample vs out-of-sample split; parameter sweep heatmap; results by VIX regime and event weeks | Each condition's effect shown in isolation, out-of-sample next to in-sample |
| M8 | Polish: docker compose, full CI, README with screenshots and architecture diagram | `docker compose up` runs everything |

After M8: add strategies (strangle, iron condor, debit spreads) through the strategy interface,
then BANKNIFTY.

## 8. Architecture rules (so expansion works later)

- The data schema includes the underlying symbol from the start (NIFTY now, others later).
- Strategies implement one small base interface; adding a strategy must not require engine changes.
- Data, engine, costs, metrics, API and frontend are separate modules with clear boundaries.
- All parameters live in config objects — no magic numbers in logic.
- Keep it simple: no abstraction that a current milestone doesn't need.

## 9. Rules for Claude Code

1. Never invent, estimate or fill in market data or results. If data is missing, say so.
2. Never hardcode expiry weekdays or lot sizes (§4).
3. One milestone at a time; stop and summarise for review at the end of each.
4. Explain non-obvious decisions in code comments and milestone notes, in plain language.
5. Write tests alongside code, including at least one hand-verified example per calculation.
   CI uses small synthetic fixtures with NSE's real column schemas; no real NSE rows are
   committed. Tests on real data (e.g. hand-traced trades) run locally and skip when the data
   cache is absent.
6. Ask before adding dependencies or changing anything in this spec.
7. Prefer clear, readable code over clever code — the owner must be able to explain all of it.
8. Commit at the end of each milestone with a clear message.

## 10. Spec changes

- 2026-10-09, before M0, approved by the owner: dated cost-rate table from primary sources
  (incl. the 1 Apr 2026 STT change); tracked top-level `reference/`, `data/` fully ignored;
  P&L in ₹, points per unit and % of premium; run data manifest; NIFTY 50 TRI benchmark and no
  unsourced margin figure; special-session and format-overlap traps; entry, expiry and
  skipped-week rules; return-on-notional Sharpe; synthetic CI fixtures; extra approved packages.
