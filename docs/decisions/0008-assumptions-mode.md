# 0008 — Assumptions mode: constraints, an equilibrium prior, distance from best

Date: 2026-11-01. Status: accepted (RT chose the defaults, 2026-10-24:
“Condor is for fun; go with the defaults and see where it takes us”).
Builds on [0006](0006-premium-expected-returns.md).

## Context

Condor’s frontier and tangency fit one historical window, so for any real
plan the “best mix” is mostly hindsight: on RT’s ETFs it loads up on whatever
won from 2019 to 2026. The forecast already blends a prior; the frontier
doesn’t. And a real plan encodes limits the optimizer can’t see (caps,
floors, a sleeve). The question to answer, for anyone: *under my assumptions
and rules, where is the best point, and how far is my plan from it?*

## Decision

1. **Constraints.** Per-asset min/max and group min/max, all linear.
   Frontier points stay PyPortfolioOpt solves with bounds and added
   constraints. The constrained tangency is the standard homogenized convex
   QP: with `y = k·w`, minimize `yᵀΣy` subject to `(μ − rf)ᵀy = 1`,
   `Σy = k`, `k·lo ≤ y ≤ k·hi`, and group limits scaled by `k`. It is exact
   and one solve, and handles any linear limit (a frontier scan is the test
   cross-check). Unconstrained paths are untouched, so legacy-pinned numbers
   cannot move.
2. **One estimator for return priors, needing no third-party table.** On
   premiums (ADR 0006):
   - Prior: equilibrium premiums `Π = δΣw_ref`. By default `w_ref` is one
     market proxy (VT) and `δ` is set so its premium is the market premium,
     which gives every asset `Π_i = market_premium × β_i`. Assets outside
     the proxy are priced by their covariance with it.
   - Market premium default: `max(MARKET_ANCHOR − rf_level, 0)`, the number
     the forecast already holds, so there is one place to change it.
   - History enters as a view on every asset with `Ω = Σ/T`, which collapses
     to `μ_post = (T₀·Π + T·μ̂)/(T₀ + T)`: the prior counts as `T₀` years of
     data. Default `T₀ = 20`. For the robust method the sample median is
     less efficient, so `T` becomes `T × 2/π`.
   - The user’s own views sit on top as ordinary Black-Litterman absolute
     views (PyPortfolioOpt), prior covariance `Σ/(T₀ + T)`.
   Expected return stays `rf_level + premium`.
3. **Distance from best: three convex gaps.** Sharpe gap to the
   (constrained) tangency; return gap at the plan’s own dispersion; dispersion
   gap at the plan’s own return. A gap with no feasible comparison is null,
   not zero. A plan that breaks a limit is told so, by name.
4. **`Assumptions` is a small validated dataclass; `AssumptionSet` is
   storage.** Saved per user as JSON. An analysis receives a **copy** in the
   request (ADR 0004’s rule: editing a saved set never moves past results).
5. **Opt-in, side by side.** History stays the default view; “Under: <set>”
   appears beside it with the user’s plan marked on both. Results are
   additive in the payload (`assumed`).

## Alternatives rejected

- *A table of published long-run assumptions:* copied third-party numbers
  to maintain; here the user states two numbers instead of ten.
- *Two estimators (table shrinkage and Black-Litterman):* the closed form
  above is both.
- *Searching along the frontier for the constrained tangency:* agreed first
  with the portfolio session, replaced by the exact QP; same answer, less
  machinery.
- *Michaud resampling:* a shrinkage heuristic with weak theory, and the
  prior already shrinks. Bootstrap stability bands on the tangency are the
  honest diagnostic, later.
- *Smallest weight changes that close the gap:* non-convex; later.

## Reopens if

- Real-return mode (T-bill vs TIPS as the risk-free), named-window scenarios,
  or stability bands are built: the next bucket, on top of this.
- The forecast fan should run under a set too.
- Assumptions mode becomes the default view.
