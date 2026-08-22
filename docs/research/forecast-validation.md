<!-- Research agent report, August 2026. Verify citations before relying on them. -->

# Validating Probabilistic Forecasts for the Condor Forecaster

*A survey of proper scoring rules, calibration testing, and honest long-horizon backtesting practice, translated into a concrete validation plan for Condor's GBM/bootstrap fan-chart feature.*

## 1. Proper scoring rules

A proper scoring rule assigns a forecaster a penalty that is minimized in expectation only by reporting their true belief distribution — it cannot be gamed by hedging or sharpening a forecast beyond what's justified. This is the right foundation for judging Condor's fan chart, because a fan chart *is* a full predictive distribution (not a point forecast), and any metric that only looks at, say, the median would reward bands that are dishonestly narrow or wide.

**CRPS (Continuous Ranked Probability Score)** is the standard workhorse for evaluating a full predictive CDF against a scalar outcome. It generalizes MAE to distributions: `CRPS(F, y) = ∫(F(x) − 1{x ≥ y})² dx`, lower is better, and it has a closed form for the Gaussian (`σ·(z·(2Φ(z)−1) + 2φ(z) − 1/√π)`, z=(y−μ)/σ) and for the lognormal — directly relevant since Condor's GBM engine produces lognormal wealth distributions. CRPS is bounded, robust to the occasional extreme outlier the way squared-error scores aren't, and reduces smoothly to MAE for a point forecast, which makes it the natural primary metric for comparing GBM vs. bootstrap fan charts.

**Log score** (`−ln f(y)`) is the proper, *local* scoring rule underlying maximum likelihood — it only cares about the density mass assigned exactly at the outcome. For financial returns this is a real liability: a single observation landing where the forecast density is near zero (a fat-tail event a lognormal model under-weights) produces an unbounded penalty that can swamp everything else in a backtest. Treat it as a secondary/diagnostic score, not primary.

**Pinball / quantile loss** scores one quantile level τ directly: `ρτ(y − q) = (τ − 1{y<q})(y − q)`. This maps exactly onto how Condor will construct its bands (quantiles at 2.5%, 17.5%, 50%, 82.5%, 97.5% for the 95%/65% bands), so per-quantile pinball loss is the natural diagnostic for *which part* of the fan is miscalibrated.

**Interval score (Winkler score)** scores a central prediction interval jointly for width and coverage: for a (1−α) interval [l, u], `IS = (u−l) + (2/α)(l−y)·1{y<l} + (2/α)(y−u)·1{y>u}`. It decomposes into sharpness (the width term) plus a calibration penalty, and is algebraically the sum of two pinball losses at α/2 and 1−α/2 — so it's a direct, single-number summary of "how good is Condor's 65% (or 95%) band," rewarding narrow bands only when they still contain the outcome.

**Python implementations:**
- `properscoring` — CRPS (ensemble and Gaussian closed-form) and Brier score; simple, numba-accelerated, but unmaintained/minimal.
- `scoringrules` (frazane) — the modern choice: CRPS, log score, and interval/quantile scores, with closed forms for many parametric families (normal, lognormal included) plus ensemble/quantile-sample variants, and numpy/JAX/torch backends.
- `scikit-learn` — `mean_pinball_loss`, `d2_pinball_score` for pinball loss (used for regression quantile evaluation, not distribution-native but fine for per-quantile scoring).
- `statsmodels` — **no proper scoring rules**; its relevance is indirect (HAC/Newey-West covariance estimators for the significance testing in §3/§5, and `QuantReg` for fitting quantiles, not scoring them).

## 2. Calibration: PIT, coverage tests, reliability diagrams

Scoring rules answer "how good is the forecast overall"; calibration tests answer the narrower, more actionable question: **"does the stated coverage mean what it says?"** For Condor's 95% band, the testable statement is literally: *across many independent forecast/realization pairs, the realized outcome should fall inside the band about 95% of the time, and violations should not cluster in time.* That is two separate claims — unconditional coverage and independence — and there are standard tests for each.

**PIT (Probability Integral Transform) histogram.** If `F_t` is the forecast CDF issued before time `t` and `y_t` the realized outcome, then `PIT_t = F_t(y_t)` should be i.i.d. Uniform(0,1) if the forecast is correctly specified. Plotting a histogram of PIT values across many (t, y_t) pairs is the standard visual: U-shaped means bands are too narrow (overconfident — reality lands in the tails too often), a hump in the middle means bands are too wide, and skew means the center of the distribution is biased. This is exactly the diagnostic used to evaluate the Bank of England's inflation fan charts and RPIX fan-chart backtests, which is the closest real-world precedent to what Condor is building.

**Formal goodness-of-fit on PIT:** Kolmogorov-Smirnov or Anderson-Darling against Uniform(0,1) (`scipy.stats.kstest`, `scipy.stats.anderson`); Anderson-Darling weights the tails more and is more sensitive to exactly the kind of miscalibration a 95% band cares about. The **Berkowitz (2001) test** transforms PIT values through the inverse-normal CDF and runs a likelihood-ratio test for standard-normal-and-independent, which is the method actually used in the BoE RPIX fan-chart backtesting literature.

**Kupiec's unconditional-coverage (POF) test:** for a nominal exceedance probability p (0.05 for a 95% band), with N observed violations out of T trials, `LR_uc = −2 ln[(1−p)^(T−N) p^N / (1−p̂)^(T−N) p̂^N] ~ χ²(1)` under the null that the true exceedance rate equals p. This is the standard first-line VaR-style backtest.

**Christoffersen's conditional-coverage test** adds an independence test on top: a model can pass Kupiec (right average exceedance rate) while still failing because violations cluster (e.g., three band breaches in one bad quarter, none for years) — exactly the "band is fine on average but useless when it matters" failure mode. It models exceedances as a two-state Markov chain and tests the transition probabilities are equal (`LR_ind ~ χ²(1)`), then combines with Kupiec into a joint `LR_cc ~ χ²(2)`.

**Reliability diagrams / calibration curves** are the visual generalization of PIT for a family of coverage levels — plot nominal vs. empirical coverage across several band widths (e.g., 50/65/80/95/99%) and check it tracks the 45° line. `scikit-learn`'s `calibration_curve`/`CalibrationDisplay` are built for binary classification but the same binning idea applies; there is no off-the-shelf continuous-forecast equivalent in a mainstream Python package, so this is a ~30-line custom plot in Condor (bin by predicted coverage level, compute empirical hit rate, plot against nominal).

None of Kupiec, Christoffersen, or PIT goodness-of-fit have a canonical, widely-used Python package — they are typically hand-rolled (they're each 10–30 lines of `numpy`/`scipy.stats.chi2`), which is fine for Condor to implement directly as engine-level test utilities.

## 3. The long-horizon problem — and its honest limits

This is the crux of validating a *multi-year* fan chart, and the honest answer is uncomfortable: **with Condor's data, formal statistical testing at the 2–5 year horizon is close to infeasible, and the field knows it.**

With ~25 years of usable history and a 2-year horizon, non-overlapping windows give you `25 / 2 ≈ 12` independent outcomes. For a 5-year horizon, `25 / 5 = 5`. No coverage test, CRPS comparison, or Diebold-Mariano test has meaningful power at N=5–12; you cannot distinguish "well calibrated" from "got lucky/unlucky" at that sample size, no matter how sophisticated the estimator. Research on long-horizon predictability is explicit about this: "you can't get around the issue of small sample sizes no matter how the data are broken down," and effective non-overlapping sample size for horizon ΔT within a fixed history shrinks as `1/ΔT`.

The obvious fix — use *overlapping* windows (roll the forecast origin forward one month/quarter at a time) — recovers apparent sample size but not information: adjacent overlapping-horizon errors share nearly all their underlying return realizations, so they are massively autocorrelated, and the effective sample size is still governed by the ~12 non-overlapping "chunks" the data actually contains. The standard corrections — **Hansen-Hodrick (1980)** and **Newey-West (1987)** HAC standard errors, using a Bartlett or similar kernel with lag length tied to the horizon — are taught as the fix, but the literature is blunt that they are **severely downward-biased exactly when the horizon is long relative to the sample**, which is precisely Condor's situation (2–5 year horizon against ~25 years of data). A block bootstrap of the test statistic itself (resample the base-frequency return series in overlapping blocks, reconstruct many pseudo long-horizon paths, and derive the sampling distribution of the score or coverage statistic empirically) is more robust than relying on HAC asymptotics, but it is bootstrapping from the *same* 25 years — it cannot manufacture regimes or tail events the sample never saw, so it narrows but does not remove the small-sample problem.

A recent paper proposing a "tile test" for exactly this setting (long horizon, limited history, financial risk backtesting) concludes plainly that "the feasibility of rigorous statistical inference diminishes substantially when combining long forecast horizons with constrained historical datasets" — there is not enough independent information to reliably separate genuine calibration from chance, even with an improved test design. Regulatory practice (e.g., Basel-style VaR backtesting, which prefers non-overlapping windows) runs into the same wall and typically supplements formal tests with judgment for anything beyond a roughly 1-year horizon.

**What practice actually falls back on, honestly:**
1. Test calibration formally *only* at horizons where the data supports it (for Condor, likely ≤ 1 year — monthly or quarterly origins give tens to low hundreds of overlapping windows, and even there treat HAC-based p-values as indicative, not decisive).
2. At 2–5 year horizons, do **descriptive** checks only: plot the handful of non-overlapping realized outcomes against the fan; report the overlapping-window exceedance rate with an explicit "not independent, no formal p-value claimed" caveat; and run **stress/case-study checks** against known severe historical episodes (2000–02, 2008–09, 2020, 2022) rather than a hypothesis test.
3. Lean on **mechanical correctness instead of empirical calibration** at long horizons: if the 1-step model is well calibrated (testable) and the multi-step aggregation is provably the right math (i.i.d. compounding for GBM's lognormal convolution; concatenation for block bootstrap), then the long-horizon band's credibility comes from verified arithmetic plus short-horizon calibration, not from a long-horizon backtest that cannot exist with enough power. This distinction — "the engine computes the right thing" vs. "the right thing matches reality" — is exactly the line Condor's automated tests vs. offline evaluation should draw (see §7).

## 4. Walk-forward design

**Expanding vs. rolling windows.** An expanding (anchored) window uses all data up to the forecast origin — more efficient parameter estimates, but blends regimes together as if they were exchangeable. A rolling (fixed-length) window adapts to the recent regime but is noisier, and the noise is not symmetric across parameters: volatility (σ) is estimated with modest data because realized variance uses squared, near-daily information, while the drift/expected-return (μ) is famously hard to pin down from any historically available sample length (the classic Merton-style point: distinguishing a small positive μ from zero needs an implausibly long sample given typical equity volatility). This matters directly for Condor: **σ estimation is where the rolling-vs-expanding choice is a real, testable engineering decision; μ estimation is where any choice is dominated by estimation noise that no amount of walk-forward cleverness removes**, which should shape both the engine design (consider shrinking μ toward a long-run/CAPM-style prior rather than trusting the rolling sample mean) and the UI honesty story (§7c).

**Purging and embargo.** López de Prado's purged/embargoed cross-validation is designed for the case where features and labels have overlapping time support; in Condor's setting the more direct risks are:
- **Overlapping-horizon labels** are unavoidable in a walk-forward study of a 2-year forecast (successive monthly origins share ~23 months of realized outcome) — this isn't leakage, it's exactly the autocorrelation problem in §3, and is handled there (HAC/block-bootstrap on the test statistic), not by purging.
- **Universe definition leakage** is the real purge/embargo analog for Condor: if the asset universe used in a walk-forward backtest is defined by "current" index membership or "assets that still exist today," that silently uses future information (a stock is in the S&P 500 today partly *because* it survived and grew) — see survivorship in §6. The fix is to freeze the universe as of each forecast origin date, not as of "today."
- **Corporate-action-adjusted prices**: retroactive multiplicative adjustments for splits/dividends are not look-ahead (they're mechanical restatements of a historical price series, not information about the future) and are safe to use as-is. The look-ahead risk is elsewhere — in vendor total-return indices or adjustment methodologies that get *revised* after the fact (rare, but check Condor's data source), and in mixing "adjusted as of forecast date" vs. "adjusted as of today" series inconsistently across a walk-forward loop.

## 5. Benchmarks to beat, and the Diebold-Mariano test

A fancy forecaster is worthless unless it beats simple alternatives; the standard rungs, from most to least naive:

1. **Zero-drift random walk** — μ=0, only σ estimated. The "do you even have a usable view on returns" baseline.
2. **Historical/empirical quantiles** — take the empirical distribution of trailing (or i.i.d.-resampled) realized returns directly, no parametric model at all.
3. **Constant-μ,σ GBM** (lognormal, closed form) — one of Condor's own candidate methods; its "naive" version uses the plain full-sample mean/std with no shrinkage or regime conditioning.
4. **i.i.d. bootstrap** of single-period returns compounded to horizon — a simpler cousin of Condor's stationary/block bootstrap candidate, useful as an even-more-naive rung to show the block structure earns its complexity.
5. **Stationary/circular block bootstrap** (Politis & Romano, 1994) — preserves autocorrelation and volatility clustering; implemented in Python by `arch.bootstrap` (`StationaryBootstrap`, `CircularBlockBootstrap`, `MovingBlockBootstrap`). This is genuinely Condor's other candidate method, not just a baseline, so the comparison of interest is method-vs-method as much as method-vs-naive.

Worth internalizing before setting expectations: in the M6 financial forecasting competition (2022–23, 100 real assets, monthly probabilistic ranking scored by RPS — the discrete analog of CRPS), only 23% of professional/academic teams beat the naive uniform benchmark on average, and only 8.6% beat it with statistical significance; the best team improved on the naive benchmark by just 2.2%. That is strong, recent, real-money evidence that naive baselines in financial forecasting are hard to beat and that most of the apparent skill in a backtest is noise — a useful calibration for how skeptically to read Condor's own comparisons.

**Diebold-Mariano test** is the right formal tool for comparing two forecasters' score series (e.g., per-period CRPS or pinball-loss differentials): it tests whether the mean loss differential is zero, using a HAC-type variance estimate with lag length tied to the forecast horizon (its motivating use case is literally h-step-ahead forecast comparison, which is Condor's exact setting) and the Harvey-Leybourne-Newbold small-sample correction, which matters given Condor's limited effective sample. Python: the `dieboldmariano` PyPI package, the `johntwk/Diebold-Mariano-Test` GitHub implementation (includes the Harvey correction), or hand-rolled on top of `statsmodels`' HAC covariance (`cov_hac` / `get_robustcov_results(cov_type="HAC")`). As in §3, treat DM p-values as meaningful at short-to-medium horizons and as descriptive-only at 2–5 years.

## 6. Pitfalls

- **Data snooping across method variants.** If Condor tries several rolling-window lengths, shrinkage targets, or GBM-vs-bootstrap parameterizations and reports whichever scored best on the same historical backtest, that backtest score is inflated by selection — the same mechanism the Deflated Sharpe Ratio (Bailey & López de Prado, 2014) and "probability of backtest overfitting" literature quantify for strategy backtests. Mitigation: fix the candidate set *before* looking at scores, hold out a strict final validation slice (e.g., the most recent 3–5 years untouched until a last check), and if a "winner" is reported, disclose how many variants were tried rather than presenting the best score as an unconditional expectation.
- **Multiple testing.** Computing CRPS, pinball at 5 quantiles, and coverage at 2 confidence levels, across 5 horizons and 3 methods, produces on the order of 100+ numbers; cherry-picking the favorable subset is the same bias in a different costume. Report the full grid (or a single pre-specified primary metric) rather than a curated highlight.
- **Survivorship in ticker choice.** Building or validating on "assets that exist today" systematically excludes delisted/merged/bankrupt names, biasing both the estimated μ and the apparent calibration optimistic. The universe used in any historical evaluation must be reconstructed as of each historical date.
- **Silent regime dependence.** A method (window length, shrinkage strength, bootstrap block length) tuned on 2010–2020 — a persistently low-rate, low-volatility, rising-equity regime — can fail in 2022 (correlated equity/bond drawdown, rate shock) without throwing any error; it's a modeling-adequacy failure that no unit test catches. Mitigation: report backtest results **stratified by sub-period** (not just pooled over the full 25 years) specifically to surface a method whose ranking versus baselines flips across regimes, and treat periodic re-evaluation as ongoing monitoring, not one-time certification.

## Summary table: scores, tests, and packages

| Tool | Purpose | Core idea | Python | Caveat for Condor |
|---|---|---|---|---|
| CRPS | Primary proper score for a full predictive distribution | `∫(F(x)−1{x≥y})²dx`; closed form for normal/lognormal | `scoringrules` (preferred), `properscoring` | Use as the headline metric; closed-form lognormal variant matches GBM directly |
| Log score | Secondary/diagnostic proper score | `−ln f(y)` | `scoringrules`, `scipy.stats.*.logpdf` | Unbounded penalty on tail misses — don't use alone on fat-tailed returns |
| Pinball / quantile loss | Score one quantile level | `(τ−1{y<q})(y−q)` | `sklearn.metrics.mean_pinball_loss`, `scoringrules` | Matches the exact band quantiles (2.5/17.5/50/82.5/97.5%) |
| Interval (Winkler) score | Joint width+coverage score for a central band | width + penalty if outside | `scoringrules` | Direct single-number summary of the 65%/95% bands |
| PIT histogram | Visual calibration check | histogram of `F_t(y_t)` should be flat/Uniform(0,1) | custom (numpy/matplotlib) | U-shape = bands too narrow; hump = too wide |
| KS / Anderson-Darling on PIT | Formal GoF for PIT uniformity | standard GoF statistic | `scipy.stats.kstest`, `scipy.stats.anderson` | AD is more tail-sensitive — relevant to the 95% band |
| Berkowitz test | PIT → inverse-normal, LR test for iid N(0,1) | `LR ~ χ²(3)` | hand-rolled | Used in BoE RPIX fan-chart backtests — good template |
| Kupiec unconditional coverage | Exceedance rate = nominal? | `LR_uc ~ χ²(1)` | hand-rolled (~10 lines) | Needs adequate N; weak at 2–5y horizon |
| Christoffersen conditional coverage | Do exceedances cluster? | `LR_ind ~ χ²(1)`, `LR_cc ~ χ²(2)` | hand-rolled | Same N caveat |
| Diebold-Mariano (+ Harvey-Leybourne-Newbold) | Compare mean score of two forecasters | HAC t-stat on loss differential | `dieboldmariano` (PyPI), `johntwk/Diebold-Mariano-Test` | Matches h-step-ahead use case exactly; small-sample correction needed |
| Newey-West / Hansen-Hodrick HAC | Correct SEs for overlapping-window autocorrelation | Bartlett-kernel HAC covariance | `statsmodels.stats.sandwich_covariance.cov_hac`, `arch.covariance.kernel` | Known to be severely downward-biased when horizon is long vs. sample length |
| Stationary / circular block bootstrap | Resample dependent series; also a forecaster in its own right | Politis-Romano random block length | `arch.bootstrap` | Candidate method *and* a way to get the sampling distribution of a test statistic without HAC asymptotics |
| Reliability diagram | Nominal vs. empirical coverage across band widths | binned observed vs. predicted | custom; `sklearn.calibration_curve` (classification-flavored) | No off-the-shelf continuous-forecast package; build a small utility |
| Closed-form lognormal quantiles | Ground truth for the GBM engine | `q_p = exp[(μ−σ²/2)T + σ√T·Φ⁻¹(p)]` | `scipy.stats.lognorm` | This is the exact "closed form" pin CLAUDE.md asks for |

## Recommendation for Condor

**(a) What an automated `pytest` suite can and should pin.** Automated tests should verify **engine correctness and internal consistency**, never real-market calibration — the latter is an inherently low-power empirical question (§3) and doesn't belong in a fast, deterministic test. Concretely:
- GBM engine: for fixed (μ, σ, T), Monte-Carlo-simulated quantiles must agree with the closed-form lognormal quantiles `exp[(μ−σ²/2)T + σ√T·Φ⁻¹(p)]` within a tolerance set by simulation error — this is the classic closed-form pin the project already favors.
- Bootstrap engine: driven on a synthetic i.i.d.-normal series with known moments, the bootstrap-implied mean/variance of compounded horizon-H wealth must converge to the known analytic values as resample count grows — a consistency test, not a backtest.
- Cross-method regression check: on that same synthetic series, GBM and bootstrap bands should agree with each other (both recover the same lognormal quantiles) — catches implementation bugs without requiring any real-data judgment call.
- A CRPS smoke test on a fixed-seed synthetic dataset generated *by* a GBM-like process: assert `CRPS(GBM) ≤ CRPS(zero-drift random walk)`. Label this clearly as a regression/sanity test in code comments, not evidence of real-world skill.
- Self-consistency tests for the Kupiec/Christoffersen/PIT-GoF *implementations*: on large synthetic samples from a known distribution, the test statistics should reject at close to the nominal rate — this validates that the formulas are coded correctly, not that Condor's real forecasts are calibrated.

**(b) What a periodic offline evaluation notebook should compute.** Run manually (e.g., quarterly), against real Condor asset data, outside CI:
- A walk-forward study (monthly origins, expanding and rolling windows, frozen per-origin universe) producing 1mo/3mo/6mo/1y/2y-ahead forecasts from each candidate method.
- At horizons with adequate replication (likely ≤ 1 year given ~25 years of history): CRPS and per-quantile pinball loss with HAC-adjusted uncertainty, Harvey-corrected Diebold-Mariano tests against each naive baseline (empirical quantiles, i.i.d. bootstrap, constant-μσ GBM, zero-drift random walk), Kupiec + Christoffersen on the 65%/95% bands, and PIT histograms with KS/Anderson-Darling as descriptive diagnostics.
- At 2–5 year horizons: descriptive-only output — the ~5–12 non-overlapping realized outcomes plotted against the fan, the overlapping-window exceedance rate with an explicit non-independence caveat, and stress case-studies against 2000–02, 2008–09, 2020, and 2022 — no p-value presented as having real statistical power.
- Regime-stratified re-runs (pre/post-2010, pre/post-2020, rolling 5-year slices) specifically to catch a method whose ranking versus baselines flips across periods.
- Fixed candidate set per run, versioned output (numbers + plots) checked into the repo, so drift and multiple-comparison exposure are both visible over time rather than a one-off leaderboard.

**(c) What the UI can honestly claim.** Supportable: language like "this range reflects historical variability in returns, estimated from trailing market data" for the fan generally, with a methodology page stating that short-horizon (≤1 year) coverage has been backtested and multi-year bands are model-based projections that could not be independently verified with statistical confidence given the available history. Avoid: bare "95% probability"/"95% chance" phrasing attached to a 2–5 year band (implies a validated calibration claim §3 shows Condor cannot back at that horizon); the unqualified word "backtested" applied to multi-year bands specifically — reserve it for the ≤1-year claims that actually have some test power, and use "modeled"/"simulated"/"based on historical statistics" for longer horizons; any suggestion that the band captures regime shifts or tail risk beyond what's in the training history; and unhedged confidence in the central/expected path, since μ (not σ) is the dominant source of long-horizon uncertainty and is the input estimated with the least precision (§4).

## References

- Gneiting & Raftery (2007), "Strictly Proper Scoring Rules, Prediction, and Estimation" — https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf
- `properscoring` (GitHub) — https://github.com/properscoring/properscoring
- `scoringrules` docs — https://scoringrules.readthedocs.io/en/latest/ and https://frazane.github.io/scoringrules/api/crps/
- `scoringutils` scoring-rules vignette (R, conceptual reference) — https://cran.r-project.org/web/packages/scoringutils/vignettes/scoring-rules.html
- scikit-learn `mean_pinball_loss` — https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_pinball_loss.html
- CRPS closed-form / scipy discussion — https://github.com/scipy/scipy/issues/23017
- Kupiec POF backtest — https://www.researchgate.net/publication/308899080_Backtesting_Value_at_Risk_Forecast_the_Case_of_Kupiec_Pof-Test
- Christoffersen conditional coverage explainer — https://metricgate.com/docs/var-backtesting-christoffersen/
- VaR backtesting thesis (Kupiec/Christoffersen overview) — https://aaltodoc.aalto.fi/bitstream/handle/123456789/181/hse_ethesis_12049.pdf?sequence=1
- Bank of England, "Understanding the fan chart" — https://www.bankofengland.co.uk/quarterly-bulletin/1998/q1/the-inflation-report-projections-understanding-the-fan-chart
- Backtesting the RPIX inflation fan charts (Risk.net) — https://www.risk.net/journal-risk-model-validation/2161302/backtesting-rpix-inflation-fan-charts
- ECB, "Fan charts 2.0" — https://www.ecb.europa.eu/pub/pdf/scpwps/ecb.wp2624~4e679bae9b.en.pdf
- Long-Horizon Predictability: A Cautionary Tale — https://www.tandfonline.com/doi/full/10.1080/0015198X.2018.1547056
- Taking stock of long-horizon predictability tests — https://www.sciencedirect.com/science/article/pii/S0304407623000052
- Biases in long-horizon predictive regressions — https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004013
- Long-Horizon Regressions when the Predictor is Slowly Varying (Valkanov) — https://rady.ucsd.edu/_files/faculty-research/valkanov/long-horizon.pdf
- Improved Inference in Regression with Overlapping Observations — https://warwick.ac.uk/fac/soc/wbs/subjects/finance/faculty1/anthony_neuberger/improved.pdf
- The Tile Test for Long-Horizon Backtesting — https://arxiv.org/pdf/2007.12431
- Anderson-Darling test with limited sample size (backtesting) — https://arxiv.org/pdf/1505.04593
- Diebold-Mariano test reference (R `forecast::dm.test`) — https://pkg.robjhyndman.com/forecast/reference/dm.test.html
- `dieboldmariano` (PyPI) — https://pypi.org/project/dieboldmariano/
- Diebold-Mariano Python implementation (GitHub, Harvey correction) — https://github.com/johntwk/Diebold-Mariano-Test
- López de Prado, *Advances in Financial Machine Learning* (purging/embargo) — https://toc.library.ethz.ch/objects/pdf03/e01_978-1-119-48208-6_01.pdf
- Purged cross-validation — https://en.wikipedia.org/wiki/Purged_cross-validation
- Bailey & López de Prado, "The Deflated Sharpe Ratio" — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Deflated Sharpe Ratio overview — https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio
- The Probability of Backtest Overfitting — https://www.researchgate.net/publication/318600389_The_probability_of_backtest_overfitting
- `arch` package, time-series bootstraps — https://arch.readthedocs.io/en/latest/bootstrap/timeseries-bootstraps.html
- Block bootstrap methods and the choice of stocks for the long run — https://doi.org/10.1080/14697688.2012.713115
- The M6 forecasting competition: Bridging the gap between forecasting and investment decisions — https://arxiv.org/pdf/2310.13357
- Benchmarking M6 Competitors — https://arxiv.org/pdf/2406.19105
- Financial density forecasts: risk-neutral vs. historical (log-score drawbacks) — https://arxiv.org/pdf/1801.08007
- Regression Diagnostics meets Forecast Evaluation: Conditional Calibration, Reliability Diagrams — https://arxiv.org/pdf/2108.03210
- scikit-learn calibration curves — https://scikit-learn.org/stable/auto_examples/calibration/plot_calibration_curve.html
