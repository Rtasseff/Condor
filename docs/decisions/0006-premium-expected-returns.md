# 0006 — Expected return = today’s T-bill + historical premium

Date: 2026-10-24. Status: accepted (RT approved the batch C
recommendations, 2026-10-24).

## Context

Run on RT’s planned ETF mix (window 2019-12-04 → 2026-10-23), the robust
tangency was 95% USFR, a T-bill fund, at Sharpe 2.55. Tangency weights
go roughly as premium ÷ variance, and USFR’s variance is ~700× an equity
fund’s, so a tiny premium wins. The premium was not real: USFR’s robust
expected return (median × 252 = 5.0%) was compared with *today’s* 4.22%
T-bill rate, while its own window had near-zero rates in 2020–21 (mean
2.9%). Two mismatches — the rate from a different period than the
returns, and a median of a trending yield — invented a 0.78% premium.
Comparing with the window-average T-bill (2.96%) does not fix it
(still 94.6% USFR): the median remains above it.

Separately, the normal method’s Ledoit-Wolf shrinkage used PyPortfolioOpt’s
default constant-variance target, which pulls every variance toward the
average: USFR 0.49% → 2.67%, STIP 2.82% → 3.84%.

## Decision

1. **Expected returns are built as `rf_level + premium`.** The premium
   is the method’s estimator (median for robust, mean for normal,
   annualized as before) applied to *excess* returns: each period’s
   asset return minus that period’s T-bill return (FRED DGS3MO, the
   same series the risk-free field uses, yield / annual factor).
   `rf_level` is the risk-free rate the analysis runs with (live FRED
   by default, or the user’s typed value). Measured this way USFR’s
   premium is −0.06% and the robust tangency becomes STIP 37 · GLDM 26
   · AVDV 16 · VT 11 · AVEM 6 · VST 4. The tangency is now independent
   of the typed rate (it maximizes premium ÷ dispersion); only the CAL
   moves.
2. **Σ stays on raw returns.** The T-bill’s day-to-day variance is
   negligible (~1e-10), and keeping Σ untouched keeps every legacy-pinned
   risk number valid.
3. **Premium mode is the default** in the CLI and the web whenever the
   T-bill history is available (cached in the store like the rate).
   Without it, both fall back to today’s raw expected returns and say
   so. `--no-premium` / `premium: false` reproduce the old numbers.
4. **The robust median itself is unchanged.** Excess returns remove its
   bias on cash-like funds (the case that bit). Revisit with a trimmed
   mean or Hodges-Lehmann if a trending non-cash asset shows it.
5. **Ledoit-Wolf uses the constant-correlation target.** Each asset keeps
   its sample variance; only correlations shrink. The planned mix moves
   15.32% → 15.30%; the low-risk end of the frontier stops being
   distorted.
6. **The forecast is untouched.** Its cash leg already earns today’s
   rate, and its centre has its own anchoring (rung C).

## Alternatives rejected

- *Window-average T-bill as the Sharpe rate:* fixes the period mismatch
  for the mean only; the robust tangency stays ~95% USFR.
- *Excess returns for Σ too:* immaterial numerically, churns pinned tests.
- *Replacing the robust median:* a legacy, deliberate method; the bug is
  fixed upstream of it.
- *Excluding cash-like tickers by rule:* a list to maintain, and wrong
  for anything cash-like we didn’t list.

## Reopens if

- A non-USD risk-free rate is needed (EUR assets analysed in EUR).
- Forecast centres should also move to `rf_level + premium`.
- A user needs the raw historical μ as the default again.
