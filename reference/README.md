# reference/

Small, hand-maintained data files that the backtest depends on. Unlike `data/` (downloaded,
never committed), everything here is tracked in git and reviewed like code.

**Rules**

- Every row cites a primary source: an NSE or SEBI circular (number and date), the Finance Act,
  RBI, PIB or the Election Commission. Never a news article, a blog, or memory.
- Nothing is estimated. If a value can't be sourced, it is left out and the gap is reported.
- Changes are explained in the commit message and the milestone notes.

**Planned files**

| File | Milestone | Contents |
|---|---|---|
| `lot_sizes_legacy.csv` | M2 | NIFTY lot size per contract for the legacy-format period (Oct 2021 – Jul 2024) |
| `special_sessions.csv` | M2 | Weekend/holiday sessions and short (Muhurat) sessions |
| `cost_rates.csv` | M3 | Statutory and exchange charges with effective-from dates |
| `events.csv` | M3 | Union Budgets, RBI policy decisions, general election results |
