# M7 pre-registration: does the NIFTY short straddle have a robust edge after costs?

**Status: approved by the owner (27 Oct 2026). NO variant has been run.** This file and
`m7_plan.toml` are committed *before* any variant is executed. The study runner records that
commit and the SHA-256 of both files, and refuses to run if either has uncommitted changes.

## 1. Question and stance

**Question:** does the baseline short straddle earn a positive return after all costs, and
does any single pre-specified change improve it robustly?

The aim is evidence, not the best historical number. Every result below is reported,
including failures. When the evidence is not strong enough, the verdict is
**inconclusive**.

## 2. The baseline, frozen (B0)

**B0** is exactly the M6 reference configuration:
- short ATM straddle, 1 lot, entry 3 full sessions before the actual expiry;
- held to expiry, settled at intrinsic value from NSE's settlement level;
- ₹20 per order brokerage, 0.5 point slippage per leg, dated statutory rates, ₹5,00,000
  capital;
- code at the commit that records this plan.

**Regression check:** B0 re-run over the full window must reproduce the trade, mark, equity
and skipped files of reference run `20261024-033815-short_straddle` **byte for byte**.
- Run per period, B0's trades must equal that run's trades in the period, value for value.
- New conditions are off by default. New trade and mark columns appear only when an exit rule
  or the alternative strike reference is active.

## 3. Periods (D1)

| Period | Dates | How it may be used |
|---|---|---|
| **Development** | 1 Oct 2021 – 30 Sep 2024 | Fit thresholds (VIX percentiles), run every test, apply the decision rule |
| **Historical validation (previously observed)** | 1 Oct 2024 – 16 Oct 2026 | Checked once per pre-registered variant. **Not untouched:** M4 already showed the baseline's 2025 and 2026 results. It can show *inconsistency*; it cannot confirm anything on its own |
| **Forward holdout** | trades entered on or after 17 Oct 2026 | Untouched. Not computed, not inspected, not tuned against until the trigger in §9 |

**Trade assignment:**
- A trade belongs to a period only if it is entered **and** expires inside it.
- The one trade that spans 1 Oct 2024 (entered in Sep 2024, expiring in Oct 2024) is in
  neither period, and is logged.
- Each period has its own equity curve from ₹5,00,000 and its own TRI buy-and-hold over the
  same dates.

**Information across the boundary:**
- Indicators may use data from before a period starts, since that is the past.
- Fitted thresholds come from development data only.
- The validation end date is fixed at 16 Oct 2026 in the plan, so newly downloaded data
  can never slip in.

## 4. What is known when (D2)

### 4.1 Audit of the baseline's entry convention

B0 does two things at the entry-day close:
1. It picks the ATM strike from **NIFTY's official close that day**.
2. It fills each leg at **that option's official closing price** (`ClsPric`) minus 0.5 point.

Neither price exists until after the session ends. M1 found that `ClsPric` matches the last
traded price only about 25% of the time, so it is a computed price, not a trade anyone was
guaranteed.

**What this means:**
- **Look-ahead in strike choice:** B0 uses the final index level to choose its strike. The
  error is at most half a strike interval, but it is information a trader didn't have.
- **Execution assumption:** a fill at the official close is approximated in practice by
  trading during the last minutes. The slippage parameter is the stand-in for that gap.

**B0 stays unchanged,** for reproducibility, and is labelled the *close-to-close convention*.

### 4.2 A realistic entry sensitivity (B0-R)

**B0-R is B0 with one change: the strike is chosen from NIFTY's close on the previous session
(t−1).** That level is known the evening before entry.
- The order is placed for the entry day's closing period and filled at that day's `ClsPric`
  minus slippage, the same fill rule as B0. The chosen strike usually isn't exactly ATM by
  then.
- B0-R is a **realism check on the baseline itself**. It is compared with B0 in pairs and
  reported, but it is **not** one of the improvement variants and is not in the Holm family.
- It also runs at slippage 1 and 2 points.

**Executable timing assumed throughout:**
- Information up to the close of t−1 (index, VIX, ADX, published event dates) is used to
  decide whether to trade and which strike.
- The order executes at the entry day's close, filled at `ClsPric` − slippage.
- Stops and take-profits are resting orders, filled by the rules in §5.

### 4.3 Information rules for filters
- **VIX:** the India VIX close on t−1.
- **ADX(14):** Wilder's ADX computed from NIFTY's daily high, low and close up to t−1. The
  first 27 sessions of data have no ADX. Those weeks are **not filtered**: they trade exactly
  as B0, and the count is reported.
- **Events (D5):** an event counts only if its date was public by t−1:
  - `known_in_advance` = true;
  - `announced_on` ≤ t−1, using the event's actual date. If the actual date was announced
    after t−1, the `originally_scheduled` date is used instead, when one exists.
  - Unscheduled events are never treated as knowable.
- **Costs:** dated rates by trade date, as now. Lot size per contract per trade date, as now.

### 4.4 Event audit (D5)

`reference/events.csv` gains `known_in_advance`, `announced_on`, `originally_scheduled`,
`announcement_source` and `announcement_url`. Every value is checked against a primary
source (RBI, PIB).

| Events | Announced | Source |
|---|---|---|
| RBI MPC FY2021-22: 8 Oct 2021, 8 Dec 2021 | 31 Mar 2021 | RBI schedule press release |
| RBI MPC 10 Feb 2022 | moved from 7–9 to 8–10 Feb on **6 Feb 2022** (originally 9 Feb, published 31 Mar 2021) | RBI rescheduling notice |
| RBI MPC FY2022-23: 8 Apr, 8 Jun, 30 Sep, 7 Dec 2022; 8 Feb 2023 | 30 Mar 2022 | RBI schedule press release |
| RBI MPC 5 Aug 2022 | moved from 2–4 to 3–5 Aug on **21 Jul 2022** (originally 4 Aug) | RBI rescheduling notice |
| **RBI MPC 4 May 2022 (off-cycle)** | **not in advance:** announced on 4 May 2022 itself | Governor's statement, 4 May 2022 |
| RBI MPC FY2023-24 (6 Apr to 8 Dec 2023; 8 Feb 2024) | 24 Mar 2023 | RBI Monetary Policy page, 2023-24 schedule |
| RBI MPC FY2024-25 | 27 Mar 2024 | RBI schedule press release |
| RBI MPC FY2025-26 | 26 Mar 2025 | RBI schedule press release |
| RBI MPC 6 Aug 2025 | moved from 5–7 to 4–6 Aug; the new dates were stated on **6 Jun 2025** (originally 7 Aug) | RBI June 2025 resolution |
| RBI MPC FY2026-27 | 23 Mar 2026 | RBI schedule press release |
| Union Budgets: 1 Feb 2022; 1 Feb 2023; 1 Feb 2024 (interim); 23 Jul 2024; 1 Feb 2025; 1 Feb 2026 | 27 Jan 2022; 26 Jan 2023; 24 Jan 2024; 6 Jul 2024; 30 Jan 2025; 27 Jan 2026 | PIB (Finance / Parliamentary Affairs) |
| Lok Sabha counting, 4 Jun 2024 | 16 Mar 2024 | Election Commission press note (PIB) |

**Checked against B0's trade windows:**
- Every event that falls in a B0 window was public by that trade's t−1, except two.
  - **4 May 2022** is not knowable, so the event filter does not skip that week.
  - **10 Feb 2022's** new date came after t−1 (4 Feb). Its original date, 9 Feb, was public
    and falls in the same window, so the filter's decision is the same.
- Three Budget announcements came just one day before t−1 (2022, 2023, interim 2024). They
  still satisfy the rule.
- Trade *tagging* (M3) is unchanged: every event, including unscheduled ones, is still tagged
  for analysis.

## 5. Variants: one change at a time (D3)

Every variant is B0 with exactly one change, run over the same periods. **The primary
settings below are frozen.** The grids are sensitivity results, shown in full and never
used to choose a setting.

| Variant | Change from B0 | Primary (frozen) | Sensitivity grid |
|---|---|---|---|
| **V1a** VIX floor | trade only if VIX(t−1) ≥ the development 33rd percentile | **13.3683** | 25th = 12.6337, 50th = 14.8550 |
| **V1b** VIX cap | trade only if VIX(t−1) < the development 67th percentile | **16.8808** | none |
| **V2** event skip | skip a week whose window holds a knowable scheduled event (§4.3) | rule as stated | none |
| **V3** stop-loss | buy back a leg once its price reaches k × its entry fill | **k = 2.0** | 1.5, 2.5, 3.0; k = 2.0 also at slippage 1 and 2 |
| **V4** take-profit | buy back a leg once its price falls to (1 − d) × its entry fill | **d = 0.5** | 0.3, 0.7 |
| **V5** ADX filter | skip if ADX(14) at t−1 is above the threshold | **25** | 20, 30 |
| Entry timing | entry 1, 2, 4 or 5 sessions before expiry | descriptive only | all four |

The percentiles are computed over the 744 development-period daily VIX closes, with linear
interpolation. No P&L was looked at.

**Stop and take-profit fill rules** (conservative):
- **When checked:** each leg, on every session after entry up to and including expiry day,
  using that contract's open, high and low.
- **Stop at S = k × fill:**
  - if the open is at or above S, the leg is bought at the **open** (a gap through the stop);
  - otherwise, if the high reaches S, it is bought at **S**.
- **Take-profit at T = (1 − d) × fill:**
  - if the open is at or below T, the leg is bought at the open;
  - otherwise, if the low reaches T, it is bought at **T**.
- **Both touched the same day:** the stop is assumed first.
- **Slippage:** every buy-back fills slippage points **above** that price.
- **No information:** a zero-volume or missing row can't trigger anything, and is counted.
- **Costs:** a buy-back pays brokerage, NSE transaction charge, IPFT, SEBI fee, stamp duty
  (buyer) and GST, from the dated table. There is no STT on a purchase.
- **After the exit:** a closed leg's value stays at its exit price. The other leg carries on,
  and pays expiry charges only if it is still open at expiry.

## 6. Comparison unit and statistics (D3, D4)

### 6.1 Paired differences

The pairs are the expiries B0 traded in the period. For each such expiry e:
- **d_pts(e)** = variant net points per unit − B0 net points per unit. A week the variant
  skips counts as **0 points**: no position, no P&L.
- **d_pct(e)** = 100 × d_pts(e) / **B0's filled premium for e**, in points.
  - This is the common, documented denominator: *percent of the baseline premium*. It is
    defined even when the variant skips, and it is the same for both sides of the pair.
  - It is **not** the variant's own "% of premium": a skipped trade has no premium of its own.
- Variant trades on expiries B0 didn't trade are counted and left out of the pairs.

**Also reported separately:** the variant's **executed-trade** mean net % of its own premium,
with its count, exactly as M3/M4 define it.

### 6.2 Tests
- **Development:** a two-sided paired t-test on d_pct, with **Holm–Bonferroni** across the
  family {V1a, V1b, V2, V3, V4, V5} (m = 6, α = 0.05).
- **Confidence intervals:** 95% percentile bootstrap of the mean of d_pct, 10,000 resamples,
  seed **20261026**. Two versions:
  - **i.i.d.:** expiries are resampled independently.
  - **Moving-block:** circular, block length 4 consecutive expiries (about a month).

**The conservative envelope (used for every verdict):**
- envelope = [**min**(lower bound i.i.d., lower bound blocks), **max**(upper bound i.i.d.,
  upper bound blocks)].
- It contains both intervals even when neither contains the other. It is *not* "whichever
  interval is wider".
- If the envelope includes zero, no improvement (and no edge) is declared.

**Assumptions and limitations of the bootstrap:**
- **i.i.d. bootstrap:** assumes the weekly paired differences are independent draws from one
  distribution.
  - Weekly trades don't overlap in P&L, so there is no *mechanical* dependence.
  - But volatility clusters: big moves come in runs, and so do big differences. Positive
    serial dependence makes i.i.d. intervals (and the t-test, which shares the assumption)
    **too narrow**.
- **Circular moving-block bootstrap (blocks of 4):** keeps month-long runs together, so
  dependence within about a month is preserved.
  - Dependence longer than a block (regimes lasting months) is still broken up.
  - Wrapping the series around (circular) joins the last weeks to the first.
  - The block length is a judgement call, fixed here before any results.
- **Both:** percentile intervals of a mean can be too narrow in small samples with heavy
  tails, as short-option P&L has: a few crash weeks dominate. Neither method can create
  information the sample lacks.
- **Diagnostics:** the lag-1 autocorrelation of every differenced series is reported.
- **Low statistical power:**
  - per-trade P&L has a standard deviation of about 72% of premium, so B0's mean has a
    standard error of about 5.8% over the ~156 development trades and about 7% over the ~106
    validation trades;
  - paired differences are less noisy for small changes, but only large effects can be
    detected;
  - an *inconclusive* verdict therefore means "the data cannot tell", not "no effect".

### 6.3 Metrics for every variant and period

All are computed in Python with the existing M4 code wherever it applies:
- **Returns:** net and gross P&L, ROI, and CAGR (flagged when the period is under two years).
- **Drawdown:** max drawdown in ₹ and %.
- **Risk-adjusted returns:** notional Sharpe/Sortino at 0% (the headline), ₹ Sharpe/Sortino at
  6.5%, and the TRI buy-and-hold over the same dates.
- **Trades:** count, share of scheduled weeks traded, win rate, average win and loss, and
  executed-trade mean net % of premium with its t-statistic.
- **Tail risk** (on the common denominator): worst expiry, and the mean of the worst 5% of
  expiries.
- **Exits:** number of stop and take-profit exits, and buy-back charges.

### 6.4 Is there an edge at all?

B0's mean net % of its own premium in each period, with both bootstrap intervals and their
envelope.
- **"Positive in both previously observed periods"** only if both periods' envelopes are
  entirely above 0.
- Otherwise **"edge not demonstrated"**.

## 7. Decision rule, fixed now (D4)

For each variant in {V1a, V1b, V2, V3, V4, V5}:

**On development:**

| Verdict | When |
|---|---|
| **Promising on development** | Holm-adjusted p < 0.05 **and** mean d_pct > 0 **and** max drawdown % ≤ B0's **and** worst-5% mean (common denominator) ≥ B0's |
| **Worse than baseline** | Holm-adjusted p < 0.05 and mean d_pct < 0 |
| **Higher mean, worse tail: not promising** | significant and positive, but the drawdown or tail is worse |
| **Inconclusive** | Holm-adjusted p ≥ 0.05 |

**Then, only for promising variants, in historical validation (previously observed):**
- **Consistent:** mean d_pct > 0 and the conservative envelope (§6.2) is entirely above 0.
- **Inconsistent:** anything else.

**Final status:** a variant that is promising and consistent is **"awaiting forward
holdout"**, never "confirmed".
- Nothing is called confirmed until it passes the same rule on the forward holdout (§9).
- Sensitivity grids and B0-R don't change any verdict. They are reported beside it.

## 8. Sensitivity

- **Cost grid:** slippage {0, 0.5, 1, 2} points × brokerage {₹0, ₹20, ₹40}, in both periods.
  - It runs for **B0**, and for any variant that the §7 rule marks promising on development.
    That rule is fixed in advance, so this is not selection after the fact.
- **V3 (k = 2)** also runs at slippage 1 and 2, because a stop places extra orders.
- **B0-R** runs at slippage 0.5, 1 and 2.
- **Plateau check:** for each grid, whether the neighbours of the primary setting have the
  same sign of mean d_pct. This is reported, never used to choose.
- **Regime breakdowns (descriptive):** B0 in each period by VIX(t−1) tercile (development
  thresholds 13.3683 / 16.8808) and by event versus non-event weeks.

## 9. Forward holdout and its trigger (defined before any forward data is collected)

- **What:** B0, and only those variants that are "awaiting forward holdout", with every
  setting exactly as frozen here (including the VIX thresholds).
- **When, a single evaluation:**
  - the first date on which the forward period holds at least **52 completed B0 trades**
    (about a year of weekly expiries, expected around Oct 2027);
  - or **31 Jan 2028**, whichever comes first.
- **Why 52 trades:**
  - it covers one full annual cycle of the scheduled events (six MPC meetings and a Budget);
  - it matches the yearly blocks reported since M4;
  - with a per-trade standard deviation of about 72% of premium, B0's standard error would be
    about 10%. That is coarse, so a single pre-declared look is all the data can honestly
    support.
- **No interim looks:**
  - forward data may be downloaded and quality-checked, but no P&L is computed or viewed;
  - the study runner refuses to compute results for any date after 16 Oct 2026 unless it is
    run as the pre-declared forward evaluation.
- **Costs:** before the evaluation, `reference/cost_rates.csv` is updated from primary
  sources for any rate change in the forward period.
- **Verdict:** the §7 validation rule applied to the forward data. Only that can produce
  **"confirmed on forward data"**.

## 10. Outputs

The study is written to `studies/<study_id>/`, which is gitignored like `runs/`:
- every run, as a normal run folder;
- `study.json`: the plan hash and commit, the run map, thresholds and verdicts;
- `comparison.csv`;
- grids as CSV;
- `regimes.csv`;
- `report.md`.

The API serves them read-only, and the dashboard displays them. Every number and verdict is
computed in Python.
