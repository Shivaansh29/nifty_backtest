# reference/

Small, hand-maintained data files that the backtest depends on. Unlike `data/` (downloaded,
never committed), everything here is tracked in git and reviewed like code.

**Rules**

- Every row cites a primary source: an NSE or SEBI circular (number and date), the Finance Act,
  RBI, PIB or the Election Commission. Never a news article, a blog, or memory.
- Nothing is estimated. If a value can't be sourced, it is left out and the gap is reported.
- Changes are explained in the commit message and the milestone notes.

**Files**

| File | Milestone | Contents |
|---|---|---|
| `lot_sizes_legacy.csv` | M2 | NIFTY lot size by trade-date range before UDiFF data starts (Oct 2021 – Dec 2023) |
| `special_sessions.csv` | M2 | Every weekend/holiday session in the window, and whether it was short (Muhurat, DR drills) |
| `cost_rates.csv` | M3 | STT, NSE transaction charges, IPFT, SEBI fees, stamp duty and GST, each with an effective-from date |
| `events.csv` | M3 | 32 RBI policy decisions, 6 Union Budgets and the 2024 election result |
