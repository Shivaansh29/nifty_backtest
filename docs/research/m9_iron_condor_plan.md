# M9 plan: NIFTY iron condor

**Status: FROZEN on 7 Nov 2026, approved by the owner. This is M9's pre-registration.** At the
freeze no condor had been run, no condor P&L had been computed, and no M9 code had been written.
Any later change is a dated, logged amendment; it never silently replaces this text.

Machine-readable twin: [`m9_plan.toml`](m9_plan.toml). It carries `frozen = true`. Its SHA-256,
this file's and the freeze commit are recorded in every M9 `study.json`.

## 1. Question

Does a weekly NIFTY iron condor have an edge after all costs, and does it improve on the
short straddle baseline (B0), especially on losses?

The aim is evidence, not the best historical number. If the data cannot tell, the verdict is
**inconclusive**. Every result is reported, including failures.

The condor is tested as its own strategy. It is not combined with the straddle, and no VIX,
event, trend, stop-loss or take-profit rule is added. Those are separate questions.

M7's results and rankings are not inputs to any M9 parameter.

## 2. Strategy rules

| Item | Rule |
|---|---|
| Instrument | NIFTY nearest weekly expiry, 1 lot per leg |
| Entry | At the close, 3 trading days before the actual expiry (same as B0) |
| ATM strike | Listed strike nearest the index close; exact midpoint goes to the lower strike (same as B0) |
| Reference premium P | Entry-day close of the ATM call + close of the ATM put, in points. **A reference price only: the ATM legs are not traded** |
| Short strikes | Sell the call nearest ATM + m×P and the put nearest ATM − m×P |
| Long wings | Buy the call nearest (actual short call + P) and the put nearest (actual short put − P) |
| Exit | Hold to expiry; settle at intrinsic value from NSE's official settlement level. No early exits |
| Costs | §6: dated rate table, ₹20 per order, 0.5 point slippage per leg, on all four legs |
| Capital | ₹5,00,000, no compounding (same as B0) |

### 2.1 Rounding to listed strikes

1. **"Listed"** means a row exists for that option type, expiry and date in the reference
   chain, whatever its volume. CE and PE strike lists are searched separately.
2. **Nearest** minimises distance to the target. Distances are rounded to 6 decimal places
   first, so floating-point noise cannot break a real tie.
3. **Exact midpoint: the lower strike,** for all four legs. This is the same rule as B0.
4. **No hunting for liquidity.** If the nearest strike has zero volume, the week is skipped. The
   rule never moves to a nearby traded strike, because then volume would change the structure.
5. **The wing is measured from the actual short strike,** not from the unrounded target.

### 2.2 Unequal wings and actual maximum loss

Rounding can make the wings differ. The real widths are used and never forced to match:

```
Wc = long call strike − short call strike
Wp = short put strike − long put strike
W  = max(Wc, Wp)
```

Before costs, at expiry, with net credit C:
- maximum profit = C, when settlement is between the short strikes;
- **maximum loss = W − C,** on the wider side, when settlement is at or beyond that long strike;
- on the narrower side the loss stops at (narrower width − C);
- breakevens = short put − C and short call + C.

Observed on entry data: 4 of 789 variant-weeks had unequal wings, always by 50 points. Those
are entry 19 Mar 2026 (all three variants) and entry 3 Jun 2024 (m = 1.25).

### 2.3 Entry eligibility

A week is skipped, and the reason logged, if any of these holds. Checks run in this order.

| # | Rule | Skip reason | Why |
|---|---|---|---|
| E1 | Reference ATM CE or PE is missing | `reference_atm_missing` | P cannot be computed |
| E2 | Reference ATM CE or PE has zero volume | `reference_atm_zero_volume` | Its close may be stale (spec trap 4), and a stale P would set all four strikes |
| E3 | A short strike equals ATM, or a long strike equals its short strike | `degenerate_strikes` | It would not be a condor |
| E4 | One of the four traded legs is missing | `leg_missing` | Existing engine rule |
| E5 | One of the four traded legs has zero volume | `leg_zero_volume` | Existing engine rule: a stale close is never a fill |
| E6 | A traded leg's lot size is unknown, or the legs differ | `lot_size_unknown`, `legs_have_different_quantities` | Existing engine rules |
| E7 | Settlement level is missing | `settlement_level_missing` | Existing engine rule |
| E8 | Close-based credit C_close ≤ 0, or W − C_fill ≤ 0 | `no_positive_credit`, `no_defined_risk` | No credit, or no risk to measure |

- **E8 uses the close-based credit,** so every cell of a slippage grid trades the same weeks.
- **P is never substituted.** The settlement column, a neighbouring strike or a previous close
  would all be invented inputs.
- **Holding-period liquidity never removes a week.** After entry, a zero-volume leg is logged
  as a stale mark and a missing row as a missing mark. The trade stays in the sample, because
  dropping it would use information from after entry.

### 2.4 Coverage, measured

Measured 6 Nov 2026 from entry-day chains and row or volume flags only. **No settlement level,
later option price or P&L was used.** Window: entries from 1 Oct 2021, expiries to 16 Oct 2026.

| Scope | Development | Validation | Spanning boundary | Total |
|---|---|---|---|---|
| Scheduled weeks | 156 | 106 | 1 | 263 |

**Excluded by each rule, per variant:**

| Rule | C1 (m = 1.00) | C2 (0.75) | C3 (1.25) | C1-R (previous close) |
|---|---|---|---|---|
| E1 reference ATM missing | 0 | 0 | 0 | 0 |
| E2 reference ATM zero volume | 0 | 0 | 0 | 0 |
| E3 degenerate strikes | 0 | 0 | 0 | 0 |
| E4 traded leg missing | 0 | 0 | 0 | 0 |
| E5 traded leg zero volume | 0 | 0 | 0 | **1** (entry 24 Mar 2026, validation) |
| E6 lot size unknown or different | 0 | 0 | 0 | 0 |
| E7 settlement missing | 0 | 0 | 0 | 0 |
| E8 no positive credit | 0 | 0 | 0 | 0 |
| **Weeks available** | **263** | **263** | **263** | **262** |

- E7 comes from reference run `20261024-033815-short_straddle`, whose `skipped.csv` is empty
  for these same expiries.
- Stale ATM never occurred: the thinnest ATM leg traded 59,748 contracts.
- Thinnest traded leg over all weeks: 14,693 contracts (C1), 42,496 (C2), 27,223 (C3).
- Credit is never near zero: C_close ÷ P ranges 0.177-0.266 for C1, 0.235-0.378 for C2 and
  0.122-0.210 for C3. Filled credit stays positive at 0.5, 1 and 2 points of slippage.
- Holding period: 0 missing and 0 stale marks in all short-leg and long-leg days for C1-C3.

**Reconciling "the entry skip rule should not remove weeks" with the skip rules.** The earlier
sentence was a forecast from the data, not an instruction to drop the rules. Both hold:
- The rules stay, because forward data or a re-dated contract could still trigger them.
- On the same-close variants they remove **0 of 263** weeks, so the forecast was right.
- C1-R removes 1 week. That week counts as 0 points in pairs, and it can't affect any verdict
  because C1-R is descriptive.
- If E1 or E2 ever fires, the week is logged, never silently repaired.

**Worked example with made-up prices:** NIFTY 24500, P = 250, m = 1 gives sell 24750 CE, sell
24250 PE, buy 25000 CE, buy 24000 PE.

## 3. Variants, fixed in advance

| Id | Short strikes (m) | Wings | Role |
|---|---|---|---|
| C1 | ATM ± 1.00×P | 1×P beyond the short strike | Primary, main version |
| C2 | ATM ± 0.75×P | 1×P beyond the short strike | Primary, pre-registered alternative |
| C3 | ATM ± 1.25×P | 1×P beyond the short strike | Primary, pre-registered alternative |
| C1-R | C1 with ATM, P and strikes from the previous session | 1×P | Realism, descriptive only |

There is no sweep for the best setting. Anything else is a new, separately pre-registered
question.

**Why C1-R is kept.** M7 found **no measurable difference** from choosing the straddle's strike
at the previous close (B0-R: development +0.63%, validation −1.42% against B0, both intervals
including zero). That does not prove the same for a condor: here P sets the strike distances,
and the same-close rule assumes the close is known while trading at it. So it stays as a
realism check, with no verdict.

**C1-R timing.** ATM, P and all four strikes come from t−1. Fills use the entry day's closes.
Reference rules E1 and E2 apply to the t−1 chain; traded-leg rules apply to the entry-day chain.

## 4. Periods

Same as M7, so results line up directly:

| Period | Dates | Use |
|---|---|---|
| Development | 1 Oct 2021 – 30 Sep 2024 | Verdicts are decided here |
| Historical validation (previously observed) | 1 Oct 2024 – 16 Oct 2026 | Checked only for variants promising on development |
| Forward holdout | Entries from 17 Oct 2026 | Not computed or inspected until the trigger |

- A trade belongs to a period only if it is entered and expires inside it.
- **Selection caveat.** Condor results on these dates are unseen, but the owner has seen how the
  straddle did, and a condor is closely related. **Historical validation can reject a variant,
  but it cannot independently confirm one.**

**Forward evaluation: M7's one-time rule, unchanged.**
- **What:** B0, and only variants that are "awaiting forward holdout", with every setting as
  frozen here.
- **When, once only:** the first date with at least **52 completed eligible B0 trades** entered
  from 17 Oct 2026, or **31 Jan 2028**, whichever comes first.
- **No interim looks.** Forward data may be downloaded and quality-checked, but no condor P&L is
  computed or viewed before then.
- **Costs:** `reference/cost_rates.csv` is updated from primary sources before the evaluation.
- **Verdict:** M7's validation rule on forward data. Only this can give "confirmed on forward
  data".
- **Guard:** the study runner refuses dates after 16 Oct 2026 outside that evaluation, and
  condors are not launchable from the CLI or API (§9), so the holdout can't be seen by accident.

## 5. Formulas

For leg i: side sᵢ = +1 if sold, −1 if bought. c_i = official close at entry. Lᵢ = its
intrinsic value at the settlement level. `slip` = slippage points per leg.

```
Lot:        q = lot size × lots          the contract's own value on the trade date; all four
                                         legs must match, or the week is skipped (E6)
Fill:       fᵢ = max(cᵢ − slip, 0)  if sold
            fᵢ = cᵢ + slip          if bought
Credit:     C_close = Σ sᵢ cᵢ
            C_fill  = Σ sᵢ fᵢ
Expiry:     V = Σ sᵢ Lᵢ              Call: max(S − K, 0)   Put: max(K − S, 0)
Gross:      gross_pts = C_close − V
            gross_rs  = gross_pts × q
Net:        net_rs    = (C_fill − V) × q − charges_rs
            net_pts   = net_rs / q
Primary:    R_P  = 100 × net_pts / P
Secondary:  ML   = W − C_fill
            R_ML = 100 × net_pts / ML
```

- **Lot size enters ₹ figures only.** `net_pts`, `R_P` and `R_ML` don't depend on it, so they
  compare across years in which the lot moved between 25, 50, 75 and 65.
- **Costs are in R_P and R_ML** through `net_pts`, including slippage, all charges and expiry
  charges.
- **P is the same for all variants in a week and never goes near zero.** The measured credit
  never approached zero (§2.4), but it differs about threefold between C2 and C3, so a
  credit-based percentage could not be compared across variants. Net credit is never the
  primary denominator. `pnl_pct_premium_*` stays in the log, labelled "% of net credit".
- **C1-R** uses its t−1 reference premium as P.
- **B0 on the same footing:** R_P = 100 × B0 net_pts / the same week's P.
- **R_ML can pass −100%** in a maximum-loss week, because ML is before charges.

## 6. Costs

### 6.1 Treatment by event

| Event | Sold leg | Bought leg |
|---|---|---|
| Entry order | Brokerage, STT on premium, NSE charge, IPFT, SEBI fee, GST | Brokerage, NSE charge, IPFT, SEBI fee, **stamp duty**, GST. No STT |
| Slippage | Fill below close | Fill above close |
| Expires worthless | Nothing | Nothing |
| Expires in the money | Assigned: SEBI fee on notional + GST on that fee | Exercised: **STT on intrinsic value** + SEBI fee on notional + GST on that fee |

Charges apply leg by leg. There is **no netting** across a spread: beyond a long strike, the
short and long legs each pay their own charges, and the payoff is capped but the costs are not.

```
Sale:      brokerage + stt_sale×Prem + exch×Prem + ipft×Prem + sebi×Prem
           + gst×(brokerage + exch×Prem + ipft×Prem + sebi×Prem)   Prem = fᵢ × q
Purchase:  brokerage + exch×Prem + ipft×Prem + sebi×Prem + stamp×Prem
           + gst×(brokerage + exch×Prem + ipft×Prem + sebi×Prem)
Assigned:  sebi_notional×Notional × (1 + gst)                     Notional = S × q
Exercised: stt_exercise×(Lᵢ × q) + sebi_notional×Notional × (1 + gst)
```

All rates come from `reference/cost_rates.csv`, by trade date for orders and by expiry date for
settlement. The Exercised line has no stamp term because of the assumption in §6.5, and no
brokerage term because no order is placed (§6.2). IPFT in the GST base and the meaning of
Notional are assumptions (§6.6, §6.7).

**Four legs against B0's two, at entry:**

| Item | B0 | Condor |
|---|---|---|
| Orders | 2 | 4 |
| Brokerage + GST at ₹20 | ₹47.20 | ₹94.40 |
| Slippage at 0.5 point | 1 point per unit | 2 points per unit |
| STT on sale | 2 legs | 2 sold legs |
| Stamp duty | None | 2 bought legs |
| Exchange, IPFT, SEBI | 2 legs | 4 legs |

Brokerage is a fixed rupee amount, so in points it weighs more when the lot is small: ₹94.40 is
3.78 points at a lot of 25 and 1.45 points at 65.

### 6.2 Primary-source findings

| Question | Finding | Status | Source |
|---|---|---|---|
| STT on exercise: basis | **Intrinsic value** since 1 Sep 2019, defined as settlement price minus strike price (in absolute terms for a put) | **Verified** | [NSE/FATAX/41919](https://nsearchives.nseindia.com/content/circulars/FATAX41919.pdf); Finance (No. 2) Bill 2019, [clause 193](https://www.indiabudget.gov.in/budget2019-20/doc/Finance_Bill.pdf) and [memorandum](https://www.indiabudget.gov.in/budget2019-20/doc/memo.pdf); [NSE levies page](https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies) |
| STT on exercise: who pays | The purchaser, meaning the option holder | **Verified** | [NSE/FATAX/56235](https://nsearchives.nseindia.com/content/circulars/FATAX56235.pdf), [63809](https://nsearchives.nseindia.com/content/circulars/FATAX63809.pdf), [73524](https://nsearchives.nseindia.com/content/circulars/FATAX73524.pdf), row 4(b) |
| STT on exercise: rate | 0.125% to 31 Mar 2026; 0.15% from 1 Apr 2026 | **Verified** | Same circulars |
| STT at final exercise applies only in the money | "levied on intrinsic value if the option contract is in-the-money" | **Verified** | [NSE Clearing STT page](https://www.nseclearing.in/clearing-settlement/equity-derivatives/securities-transaction-tax) |
| Bought ITM index options | Final exercise is automatic, European style, and cash settled | **Verified** | [NSE Clearing settlement mechanism](https://www.nseclearing.in/clearing-settlement/equity-derivatives/settlement-mechanism) |
| SEBI fee on exercised or assigned options | Turnover is "additionally computed" on notional value for **both** exercised and assigned options | **Verified** | SEBI (Payment of Fees) (Amendment) Regulations 2019, Explanation (B), in [NSE/FA/40632](https://nsearchives.nseindia.com/content/circulars/FA40632.pdf) |
| Notional value definition | No fee-specific definition found. Settlement level × quantity kept from M3 | **MODELLING ASSUMPTION (§6.7)** | [Stock Brokers Regulations 2026](https://www.sebi.gov.in/sebi_data/attachdocs/jan-2026/1767852346757.pdf) and [1992 Regulations](https://www.sebi.gov.in/acts/stockreg1.pdf), Explanation (B) |
| GST on IPFT | No primary text found, and broker practice differs | **UNVERIFIED MODELLING ASSUMPTION, not a statutory requirement (§6.6)** | [Zerodha](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/ipft-charges), [Angel One](https://www.angelone.in/knowledge-center/online-share-trading/what-is-a-contract-note-and-how-to-read-it) |
| NSE charge, IPFT on exercise | Circulars price these on premium value. None mentions a charge on exercise or assignment | **Absence of a rule, not a positive statement** | [FA56129](https://nsearchives.nseindia.com/content/circulars/FA56129.pdf), [FA64232](https://nsearchives.nseindia.com/content/circulars/FA64232.pdf), [FA73061](https://nsearchives.nseindia.com/content/circulars/FA73061.pdf) |
| Stamp duty on purchase | 0.003%, buyer, on the premium | **Verified** | [Indian Stamp Act, s.21 proviso and Schedule I](https://dor.gov.in/files/inline-documents/Indian_Stamp_Act_1899.pdf); [SEBI FAQ](https://www.sebi.gov.in/sebi_data/faqfiles/dec-2021/1639980911330.pdf) |
| **Stamp duty on cash exercise** | **No source addresses it.** The Act values options at "the premium paid by the buyer", and cash exercise pays no premium. M9 therefore models ₹0 | **MODELLING ASSUMPTION, not a verified legal fact (§6.5)** | Interpretation of the Act above. The 2019 Collection Rules could not be fetched (India Code 504) |
| Brokerage on exercise | No order is placed, so ₹0, as for short legs. Some brokers may charge | **Assumption** | Run config; brokerage grid covers orders only |

**Not read directly:** the consolidated text of ss.98-99 of the Finance (No. 2) Act 2004
(`indiacode.nic.in` and `incometaxindia.gov.in` refused automated access). The 2019 finding
rests on the Bill's amending clause, NSE's circular on the enacted Act, and
[BSE's April 2025 master circular](https://www.bseindia.com/downloads1/Master_Circular_Finance_April_2025.pdf).
NSE's levies page shows the basis alongside the 2026 rates, so it was not changed since.

### 6.3 Correction needed in `reference/cost_rates.csv`

The two `option_exercise` rows say `basis = settlement_value`, and the notes say to verify it.
**That basis has been out of date since 1 Sep 2019.** Using the settlement level would overstate
this STT many times over. The change at implementation:
- set `basis` to `intrinsic_value` and cite FATAX41919 and the 2019 clause;
- leave rates unchanged. B0 never pays this charge, so its results can't change;
- widen the `option_assignment` note to cover exercised options.

Editing the file changes the reference-file hashes in new runs' `manifest.json`. The byte-for-byte
check covers trades, marks, equity and skipped files, which are unaffected.

Also noted: NSE/FA/73061 refers to the Sep 2024 circular as "NSE/FA/64323", but that URL is a
404. `FA64232`, cited by the rate table, is the real document with the Rs 35.03 rate.

### 6.4 Hand-calculated examples (made-up prices, real dated rates)

Entry 2 Jun 2025, expiry 5 Jun 2025, lot 75, P = 250. Sell 24750 CE at 40 and 24250 PE at 45;
buy 25000 CE at 12 and 24000 PE at 15. Slippage 0.5, brokerage ₹20.

C_close = 58, C_fill = 56, W = 250, ML = 194. Entry charges = ₹104.29.

| Settlement | Region | V | Gross ₹ | Expiry charges ₹ | Net ₹ | Net pts | R_P | R_ML |
|---|---|---|---|---|---|---|---|---|
| 24,600 | Between short strikes | 0 | +4,350.00 | 0.00 | +4,095.71 | +54.61 | +21.84% | +28.15% |
| 24,850 | Between short and long call | 100 | −3,150.00 | 2.20 | −3,406.49 | −45.42 | −18.17% | −23.41% |
| 25,100 | Beyond long call | 250 | −14,400.00 | 13.82 | −14,668.11 | −195.57 | −78.23% | −100.81% |

At 25,100 the expiry charges include ₹9.375 of STT on the long call's ₹100 intrinsic value
(0.125% × 100 × 75). These become fixed test values.

### 6.5 Stamp duty on cash exercise: an open uncertainty

**This is a modelling assumption based on statutory interpretation. It is not a directly
verified legal fact, and no M9 document may present it as one.** M9 charges ₹0 because the Act
values options at the premium paid by the buyer, and cash exercise pays no premium. No primary
source was found that states this for cash-settled exercise, and the 2019 Collection Rules
could not be read. If they become readable, or a primary source settles the point, the outcome
is logged as a dated amendment.

**Hypothetical sensitivity cases.** Two hypothetical charges were measured on 6 Nov 2026 from
the 263 B0 weeks of run `20261024-033815-short_straddle`, using only entry index close,
settlement level, ATM premium and lot size. **No P&L column was read, no condor strike was built
and no condor leg was priced.** Both use the 0.003% rate.

| Hypothetical charge, per week | Mean pts | Max pts | Max ₹ | Total ₹, 263 weeks | Mean % of P | Max % of P |
|---|---|---|---|---|---|---|
| A. On intrinsic value, using \|settlement − entry close\| as the base | 0.0070 | 0.0307 | 2.30 | 97.93 | 0.0029 | 0.0108 |
| B. On settlement × quantity, a stress with no legal basis found | 0.6410 | 0.7865 | 58.90 | 9,181.49 | 0.2758 | 0.4909 |

These are **hypothetical sensitivity cases, not estimates and not legally established limits**. No
source establishes that a charge exists, or its base or rate, so a real charge could differ from
both, including by being higher. Arithmetically, both assume every week pays on one exercised
bought leg, but at most one bought leg can finish in the money, and in many weeks none will. Case
A's base also exceeds intrinsic value, because a bought strike lies well away from the entry close. In
Q2's unit, the cases would reduce mean d_pct by 0.0029 for A and 0.2771 for B. For
scale, a condor's entry slippage is 2 points per unit, against case A's mean of 0.0070 points.

**What can't be said yet.** Whether a verdict depends on this can only be known after the run,
so this plan makes no such claim in advance.

**Measured after the run.** The stamp sensitivity in §7 recomputes cases A and B exactly from
`legs.csv`, on the legs that were really exercised, and reports the change in every affected
figure. The ₹0 assumption and this uncertainty are repeated in `report.md`, in
`docs/milestones/M9.md` and in the README.

One broker's fee page, [Interactive Brokers India](https://www.interactivebrokers.com/en/accounts/fees/indiaStockExchangeFees.php),
states stamp duty on exercise and assignment at 0.015% of delivery value, and on strike value for
currency options. Index options have no delivery, so this does not settle the point, and it is not
primary. It is recorded because it shows a charge at exercise can't be ruled out by inference alone.

### 6.6 GST on IPFT: a modelling assumption

**Verified:** GST is 18% on the exchange's financial services (Notification 11/2017), and NSE
collects IPFT from members as an ad-valorem contribution ([FA46730](https://archives.nseindia.com/content/circulars/FA46730.pdf)).
The contract note format leaves tax to "the applicable GST Laws" ([NSE/INSP/61999](https://nsearchives.nseindia.com/content/circulars/INSP61999.pdf)).

**Not found:** any NSE, SEBI or CBIC text that states whether GST applies to IPFT. The full text of
Notification 12/2017, the services exemption list, could not be fetched, so **the absence of an
exemption is not verified**.

**Contract-note comparison, 7 Nov 2026.** No published contract note with figures was found that
shows how GST is computed when IPFT is present. A sample note from TradeSmart returned 403.
Published descriptions of contract notes and charges are not primary, and they disagree:

| Broker | What it says | IPFT in the GST base? |
|---|---|---|
| [Zerodha](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/ipft-charges) | IPFT is billed inside exchange transaction charges, "+ 18% GST" | Yes |
| [Angel One](https://www.angelone.in/knowledge-center/online-share-trading/what-is-a-contract-note-and-how-to-read-it) | Taxable value = brokerage + exchange charges + SEBI fee + IPFT | Yes |
| [Fyers](https://community.fyers.in/blogs-gdppin8d/post/how-to-read-a-contract-note-and-why-it-matters-UkSwTnQ1GJMY2VR) | Taxable value covers SEBI fee, clearing and exchange charges; NSE IPFT is a separate row after the taxes | Apparently no |
| [Kotak Neo](https://www.kotakneo.com/support/what-are-the-key-enhancements-made-in-contract-note/) | Taxable value = brokerage + exchange charges + SEBI fee | Not listed |
| [Tradejini](https://www.tradejini.com/support/knowledge-base/know-your-broker/charges/statutory-and-exchange/what-are-ipft-charges) | IPFT itemised separately; GST not mentioned | Not stated |

**Limitation:** the treatment can't be settled from contract notes either. A real note with
figures, checking whether GST equals 18% with or without IPFT, would settle one broker's
practice, not the law.

**Treatment, accepted by the owner on 7 Nov 2026:** M9 includes IPFT in the GST base as the
conservative, higher-cost reading. **It is an unverified modelling assumption, not a confirmed
statutory requirement.** The alternative, IPFT excluded, is kept as a sensitivity (§7). It is
also the M3-M7 treatment.

**One setting, applied everywhere.** The cost model gains `gst_on_ipft`, default **false**:
- **Unchanged at false:** every historical path (CLI `backtest`, API launches, M7's study and its
  re-runs, M3/M4 code and tests). B0 reproduces byte for byte.
- **Set once, in the TOML's `[costs]`:** M9's study sets it **true** for every run it makes. That
  covers B0, C1-C3, C1-R, every cost-grid cell and every sensitivity, so both sides of each pair
  share one GST base.
- **Overrides refused:** the loader refuses any variant or grid cell that sets it, and
  `study.json` records the value used.

**Size:** B0 pays ₹1.72 more in total over 263 weeks, at most ₹0.03 a week. A condor whose four leg
premiums summed to 2×P every week, a hypothetical sizing, would pay ₹3.46, or 0.0001% of P on
average.

### 6.7 SEBI notional value: a modelling assumption

**Verified:** turnover is premium traded, "additionally computed" on the "notional value" of
option contracts exercised or assigned. The wording is the same in the 1992 Regulations (Schedule
IV, Explanation (B)) and the 2026 Regulations, and neither defines the term.

| Candidate | Where it comes from | Established as this fee's basis? |
|---|---|---|
| (Strike + premium) × quantity | Footnote to turnover tables in SEBI's [2010](https://www.sebi.gov.in/sebi_data/attachdocs/1311148149770.pdf) and [2012](https://www.sebi.gov.in/sebi_data/attachdocs/1389094067302.pdf) Handbooks | **No.** A statistical turnover definition, not tied to this fee or to exercised contracts. Not found in the 2025-26 SEBI publications checked |
| Strike × quantity | Interactive Brokers India's fee page, for exercise and assignment | **No.** One broker's statement, though the only one found that speaks to exercise directly |
| Settlement level × quantity | M3 assumption | **No.** No source found |

SEBI's 2024 letter to BSE, as reported, concerns the exchange's annual regulatory fee, not this
broker fee, and the reports give no formula. I read reports of it, not the letter.

**Treatment:** settlement level × quantity stays, labelled as an assumption. Nothing was
substituted, because neither alternative is established.

**Size:** the fee on notional is ₹1.18 per crore, so the base barely matters. On B0's 263 assigned
legs the fee totals ₹361.14. Strike × quantity changes that by −₹0.10, and (strike + entry premium)
× quantity by +₹2.01, each at most ₹0.09 a week. For a condor, two in-the-money legs every week on a
base differing by max(\|move\|, P) would change costs by ₹10.48 in total, or 0.0003% of P on average.
That is a hypothetical sizing, not a limit. §7 measures both alternatives exactly after the run.

## 7. Statistics and decision rule

Statistics reuse M7's methods. The study's fixed seed is **20261106**.

**Q1. Does the condor have an edge on its own?**
- Mean R_P per period, for C1-C3 and B0.
- 95% percentile bootstrap intervals of the mean, i.i.d. and circular moving-block (4 consecutive
  expiries), 10,000 resamples. The conservative envelope is the lower of the two lower bounds to
  the higher of the two upper bounds.
- "Positive in both previously observed periods" only if both envelopes are entirely above 0,
  and even then "awaiting forward holdout". Otherwise "edge not demonstrated".
- Also reported, with no verdict: mean R_ML and % of net credit.

**Q2. Does it improve on B0?**
- Paired by expiry as M7 §6.1. `d_pct = 100 × (variant net_pts − B0 net_pts) / B0 filled
  premium`. A skipped week counts as 0.
- Two-sided paired t-test on development, Holm across {C1, C2, C3}, α = 0.05.
- The tail metric is the mean of the worst 5% of expiries, in B0-premium units.
- M7 §7's verdicts apply unchanged, repeated here so this file stands alone:

| Development verdict | When |
|---|---|
| Promising on development | Holm-adjusted p < 0.05 **and** mean d_pct > 0 **and** max drawdown % ≤ B0's **and** worst-5% mean ≥ B0's |
| Worse than baseline | Holm-adjusted p < 0.05 and mean d_pct < 0 |
| Higher mean, worse tail: not promising | Significant and positive, but drawdown or tail is worse |
| Inconclusive | Holm-adjusted p ≥ 0.05 |

- Validation runs only for a promising variant. **Consistent:** mean d_pct > 0 and the
  conservative envelope entirely above 0. Anything else is inconsistent.
- Promising and consistent gives "awaiting forward holdout", never "confirmed".

**How to read Q2 honestly.** A condor gives up premium, so "worse than baseline" can mean only
"collected less", and "promising" needs a significantly higher mean, a high bar for a capped
structure. The rule stays unchanged, and Q3 must be read beside it. M7's power limits apply:
**inconclusive is a likely outcome.**

**Q3. Is it a better risk trade-off? (reported, no verdict)**
For each variant and B0: net ₹ P&L, the drawdowns in §8, net P&L ÷ max drawdown, worst trade,
mean of the worst 5% of expiries, win rate, and how often the maximum loss was reached. A better
ratio here is a description, not evidence of an edge.

**Realism and sensitivity (reported, never used for a verdict or to choose a setting)**

| Check | Runs |
|---|---|
| C1-R | Paired against C1, on B0's premium as denominator, both periods |
| Slippage | C1 and B0 at 0.5, 1 and 2 points per leg |
| Brokerage | C1 and B0 at ₹0, ₹20 and ₹40 per order |
| Stamp on exercise | C1-C3, cases A and B of §6.5, computed from `legs.csv` |
| SEBI notional | B0 and C1-C3 on strike × quantity and on (strike + entry fill) × quantity, §6.7, computed from `legs.csv` |
| GST base | B0 and C1-C3 with IPFT excluded from the GST base, §6.6, computed from each charge line |

**The brokerage grid is crossed with slippage (9 cells).** A condor pays for twice as many orders
as B0, and the fixed rupee fee costs more points when the lot is small, so slippage alone would
miss that. These cells run unconditionally for C1, unlike M7's grid, which ran only for B0 and
promising variants, because C1 is the main version and cost-sensitive by construction. A variant
the rule marks promising also gets the grid.

**The stamp sensitivity changes no verdict.** Verdicts are always computed on the ₹0 assumption.
For each primary and period the report prints the adjusted mean R_P, mean d_pct, Holm-adjusted p
and what the verdict would be under cases A and B. Only exercised bought legs are charged; B0
has none. If a verdict would differ, the report says so beside it, naming the case, and that
verdict must always be quoted with the caveat.

## 8. Comparable units

| Metric | Unit | Used for |
|---|---|---|
| Trade return | R_P, R_ML | Lot-free comparison across years |
| Pairs | d_pct on B0's premium | Q2 verdict, tail |
| Drawdown for the verdict | M7's ₹ max drawdown % | Rule unchanged. Fair within a pair, because both sides hold the same lot that week |
| **Lot-free drawdown (new)** | Peak-to-trough of the cumulative sum of daily `notional_net` returns | Q3, cross-year reading |
| Sharpe, Sortino | Notional, as in spec §6 | Headline; ₹ version alongside |
| ₹ totals | Actual lot size | Equity curve only. Never used across years without the lot-free figure beside it |

## 9. What must be built

**Scope is one-time and deliberate.** Spec §8 says a new strategy must not need engine changes,
but the engine was built short-only. This generalises it once; later debit spreads then need no
engine change for bought legs. The spec records the exception.

### 9.1 Reference chain without look-ahead

`legs()` gets the chain that information rules allow, under its existing signature:

- `Strategy` gains `uses_reference_prices: bool = False`. `ShortStraddle` leaves it False, so B0
  and B0-R call `legs()` exactly as now.
- For a strategy with it True and `strike_reference = previous_close`, the engine queries
  t−1 rows with `expiry IN (stated, actual)`, the same re-dating handling as the daily closes.
- It passes that chain and the t−1 index close to `legs()`. Same-close runs pass the entry chain.
- The returned legs are then checked and filled against the **entry-day** chain only.
- Duplicate rows give `ambiguous_reference_chain`; an empty chain gives
  `reference_chain_missing`.
- `SkipWeek` moves to `strategies/base.py` so strategies can raise E1-E3. The engine keeps
  importing it under the same name.

Look-ahead test: changing every entry-day close must leave C1-R's chosen strikes unchanged.

### 9.2 Engine

| Area | Design |
|---|---|
| Leg key | `leg_id` of side + type + strike replaces the `CE`/`PE` key. Duplicates are refused |
| Entry fills | §5. Sold legs keep today's code path, so B0's values and order don't change |
| Signed P&L | `premium_*_points`, `value_at_expiry_points` and marks become Σ sᵢ × value. All sᵢ = +1 gives B0 the same numbers |
| Expiry settlement | Sold ITM: `short_expiry_charges`, unchanged. Bought ITM: new `long_expiry_charges` |
| GST base | New cost setting `gst_on_ipft`, default false. With true, GST also covers IPFT (§6.6). M9's study sets it true for every variant |
| Early buy-backs | **Not applicable to M9.** A strategy with bought legs plus an exit rule raises a config error. B0's sold-leg exits don't change |
| Daily marks | Each leg at its close, signed. Zero volume on any leg sets `stale_mark`; a missing row sets `missing_mark`, and that day's value and equity stay empty, never filled. Entry-day and expiry-day handling are as now |

### 9.3 Files: additive only

- **B0 is unchanged.** `trades.csv`, `marks.csv`, `equity.csv` and `skipped.csv` keep the same
  columns in the same order, byte for byte.
- **New per-leg files, written only for multi-leg strategies:**
  - `legs.csv`, one row per trade per leg: `trade_id, leg_id, side, option_type, strike,
    entry_close, entry_fill, quantity, lot_size, lot_size_source, intrinsic_at_expiry,
    expiry_status, pnl_points_gross, pnl_rs_gross, slippage_rs, charges_rs, pnl_rs_net`, plus
    each charge line;
  - `leg_marks.csv`, one row per leg per day: `trade_id, leg_id, date, close, stale, missing`.
- **New condor-only columns in `trades.csv`:** `reference_atm`, `reference_premium_points`,
  `reference_date`, `wing_call_points`, `wing_put_points`, `max_loss_points`,
  `pnl_pct_reference_premium_net`, `pnl_pct_max_loss_net`, `legs_stale_days`.
- **One-strike columns are blank for condors** (`strike`, `ce_*`, `pe_*`). They are never filled
  with a made-up "main" strike.
- **Historical B0 runs get nothing invented.** No file is rewritten or backfilled, and their API
  `legs` field is `null`, not derived.

### 9.4 Study runner

M7's `load_plan` stays as it is, for files without `schema_version`, so M7 can still be
re-run and its "exactly one change" check isn't weakened. For `schema_version = 2`:

| Check | Rule |
|---|---|
| Declared structures | Each `[[structures]]` entry has a known strategy and a closed list of parameters. Unknown keys are refused |
| A primary's one change | A primary may differ from B0 in **only** its `structure`. Every other setting must equal B0's |
| Sensitivity and realism | `of` a variant, exactly one change, as in M7. They may not change `structure` |
| Structures | C1-C3 differ in `short_multiple` only |
| Holm, periods, holdout | M7's checks unchanged |
| Hash and commit | M7's check unchanged, plus refusing `frozen = false` |
| GST base | `gst_on_ipft` comes only from `[costs]` and applies to every run; a variant or grid cell that sets it is refused |

Also needed: an unconditional grid list, `pair()` with an explicit denominator for C1-R against
C1, the stamp and notional sensitivities of §7, and R_P, R_ML and lot-free drawdown in `study.json`,
`comparison.csv` and `report.md`. The report must print which verdicts are verdicts and which
are descriptions.

### 9.5 API, OpenAPI, TypeScript and dashboard

| Layer | Change |
|---|---|
| `TradeRecord` | Blank-able one-strike fields become optional; §9.3 columns are added as optional. B0 responses keep the same values |
| New schemas | `LegRecord`, `LegMark`; `TradeDetail` gains `legs` and `leg_marks`, `null` for B0 |
| Study schemas | `ComparisonRow` gains the new metrics; the plan info gains structures |
| OpenAPI, TS | Regenerate `frontend/src/api/openapi.json` and `schema.d.ts`. The Docker test still compares them |
| `TradeDrillDown.tsx` | Multi-leg trades show one row per leg: side, type, strike, close, fill, value at expiry, ₹ gross and net, charges. Also wing widths, maximum loss, R_P, R_ML, and each leg's daily marks. Straddle view unchanged |
| `TradeTable.tsx` | Strike column shows the four strikes for condors, and `—` is never replaced by a guess |
| Research page | Q1-Q3 next to B0, and the grid. Verdicts visually separate from descriptive figures |
| Launch form and `POST /api/runs`, CLI `backtest` | **Unchanged: straddle only.** Their default end date is today, so launching a condor could display holdout results. Revisit after the forward evaluation |

The API and dashboard still compute nothing; all numbers come from Python.

## 10. Tests and acceptance

| Area | Test |
|---|---|
| Payoffs | The three hand-calculated examples in §6.4, for P&L in all units and each charge line |
| Payoff edges | Settlement exactly at a short strike and at a long strike; put side mirrors the call side; unequal wings give W − C |
| Fills | Sold below and bought above the close; sold fill floors at 0 |
| Costs | Each line, on both sides of the 1 Oct 2024 and 1 Apr 2026 rate changes; exercised STT on intrinsic value, never on the settlement level; no netting |
| GST setting | Default false everywhere outside M9's study; the M9 study passes true to every run; B0 under the IPFT-excluded sensitivity equals the reference run's charges |
| Stamp sensitivity | A hand-calculated exercised leg under cases A and B; legs that expire worthless and sold legs are not charged; B0 unchanged; the ₹0 verdict is never overwritten; a forced verdict difference is printed beside the verdict |
| Strike selection | Rounding, every tie, separate CE and PE lists, unequal wings, sparse strikes |
| Skips | E1-E8 each, in order, with its logged reason |
| Stale and missing marks | Zero-volume leg flags the day and keeps the trade; a missing row leaves the day empty, with no fill or carry-forward; both count per leg |
| Look-ahead | §9.1 mutation test |
| Regression | With `gst_on_ipft` false, B0 reproduces `20261024-033815-short_straddle` **byte for byte** in trades, marks, equity and skipped. With it true, only GST and what depends on it change, by exactly 18% of IPFT |
| M7 | `m7_plan.toml` loads as before; M7 safeguards tests still pass; a schema 2 plan with a second change or `frozen = false` is refused |
| Real data (local) | Two C1 trades traced independently to raw NSE files: the first development week, in expiry order, with a bought leg in the money, and the first with none, both picked by code. They stay in every statistic |
| Comparability | C1-C3 and B0 share dates, capital, rate table and cost settings, checked from saved configs |
| Isolation | Condor runs can't be launched by API or CLI; no study row has a date after 16 Oct 2026 |
| Frontend | Four-leg drill-down, a null-legs B0 trade, and fixtures to 12 digits as in M6 |

**Done when:** all existing checks and CI jobs pass, the study report and research page show
C1-C3 next to B0, and `docs/milestones/M9.md` documents the three premium-distance variants, the
sensitivity method, the §6.5 uncertainty and explain-back questions.

**Order:** owner approves the freeze → set `frozen = true`, apply §13 and commit this plan with
its TOML → engine and tests on synthetic data, with no condor on real data → trace two trades →
run the study once → validate → report.

The trace comes after the freeze because it shows real condor results. A bug it finds is fixed
in the code and recorded; it can't change the frozen rules without a logged amendment.

## 11. Decisions

| # | Decision | State |
|---|---|---|
| 1 | M9 as a new milestone, recorded in CLAUDE.md at the freeze | Approved |
| 2 | Rules and eligibility, §2-§3 | Approved at the freeze, 7 Nov 2026 |
| 3 | Q1-Q3, formulas and units, §5, §7, §8 | Approved at the freeze, 7 Nov 2026 |
| 4 | Implementation and tests, §9-§10 | Approved at the freeze, 7 Nov 2026 |

## 12. Settled before the freeze

The owner accepted these on 6 Nov 2026.

1. **Stamp duty on cash exercise:** ₹0, as a documented modelling assumption from statutory
   interpretation, **not a verified legal fact**. Its sensitivity cases are in §6.5.
2. **Brokerage on exercise:** ₹0, as a stated assumption.
3. **Trade traces:** on C1, the first development week with a bought leg in the money and the
   first with none, picked by code in expiry order. They stay in every statistic.
4. **Brokerage grid:** yes, the 3 × 3 grid in §7.

Assumptions that remain open by nature: stamp on cash exercise (§6.5), IPFT in the GST base
(§6.6), notional value (§6.7), brokerage on exercise (§6.2), and no NSE or IPFT charge on exercise,
which rests on the absence of a rule (§6.2).

## 13. CLAUDE.md changes, applied at the freeze

Applied on 7 Nov 2026 in the freeze commit, word for word as below.

**§7, new row after M8:**

```markdown
| M9 | Iron condor study (`docs/research/m9_iron_condor_plan.md`): one-time engine generalisation to signed multi-leg positions, three pre-registered premium-distance variants against B0, cost and stamp sensitivities; no sweep and no added filters | Tests pass; B0 reproduces byte for byte; two condor trades traced by hand; study run once and reported with its verdicts; forward evaluation stays one-time |
```

**§7, line after the table, replacing the current sentence:**

```markdown
After M9: add further strategies (strangle, debit spreads) through the strategy interface,
then BANKNIFTY.
```

**§10, new entry:**

```markdown
- 2026-11-07, before M9, approved by the owner: M9 added as an iron condor study under the
  pre-registration `docs/research/m9_iron_condor_plan.md` (machine-readable twin
  `docs/research/m9_plan.toml`). One-time exception to §8: the engine is generalised to signed
  multi-leg positions so a strategy with bought legs can run; after this, new option
  structures need no engine change for bought legs. B0 must reproduce byte for byte.
  Exercised bought legs pay STT on intrinsic value and the SEBI fee on notional, and
  `reference/cost_rates.csv` is corrected to the intrinsic-value basis in force since
  1 Sep 2019. Labelled, unverified modelling assumptions, each with a reported sensitivity:
  stamp duty on cash exercise is ₹0 (statutory interpretation, not a verified legal fact);
  SEBI notional is settlement level × quantity; IPFT is in the GST base for M9's study only,
  with the historical default (IPFT excluded) unchanged everywhere else. Brokerage on
  exercise is ₹0, an assumption. Condors stay off the CLI and API launch paths until the
  forward evaluation.
```
