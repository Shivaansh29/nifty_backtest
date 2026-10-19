# Test fixtures

**Synthetic data only.** These files copy the exact column layout of NSE's two F&O bhavcopy
formats (including the legacy format's trailing comma), but every value is made up. No real NSE
rows are committed to this repository (spec §9, rule 5). Tests on real data run locally and are
skipped when `data/` is absent.

Both files describe the same imaginary trading day (2024-02-01) and the same contracts, so a
test can check that normalising either format gives identical rows. They include rows the
normaliser must drop (a NIFTY future, a BANKNIFTY option, a stock option) and one zero-volume
NIFTY put whose close (95.50) is a stale carried-forward price.
