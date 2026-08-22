<!-- Research agent report, August 2026. 'Measured' figures were computed on this repo's .condor_cache price files; verify citations before relying on them. -->

# Forecasting Portfolio Wealth 1–5 Years Ahead

## A method survey for the Condor Forecaster, with honest uncertainty quantification

*Research note, August 2026. Empirical figures marked "measured" were computed on Condor's own `.condor_cache/*_10y.csv` price files (daily adjusted closes, 2016-08-19 → 2026-08-19, n ≈ 2 512 daily log returns per ticker) using the environment in `.venv` (numpy 2.4.6, pandas 3.0.5, statsmodels 0.14.6, scipy 1.17.1).*

---

## 0. Framing: three uncertainties, and which one actually bites at 2 years

Any fan chart is answering "what could wealth be in *T* years?" There are three distinct reasons we don't know, and they are not the same size:

| Source | What it is | Grows with horizon like |
|---|---|---|
| **Path uncertainty** | Even with μ and Σ known exactly, the realized sequence of returns is random | SD ∝ √T |
| **Parameter uncertainty** | We estimated μ and Σ from a finite window; they are wrong by a known-ish amount | SD ∝ T (for μ) — *linearly* |
| **Model uncertainty** | The whole i.i.d.-lognormal / stationarity assumption may be wrong; regimes shift; the company changed | Unbounded, not quantifiable from the data |

The first is what a naive Monte Carlo shows. The second is the one nearly every retail tool omits, and the one that grows fastest. The third is why the chart needs prose next to it.

### The one formula that organizes the whole survey

Under i.i.d. log returns with annual volatility σ, an estimation window of **N** years, and a forecast horizon of **T** years:

```
Var(cumulative log return over T) ≈  σ²·T          (path)
                                  +  T²·σ²/N       (error in μ̂, since SE(μ̂) = σ/√N)

ratio param/path = T/N
band-width inflation factor = √(1 + T/N)
```

This is the Merton (1980) result in fan-chart form: **the precision of μ̂ depends only on the calendar span of the sample, never on the sampling frequency**. Ten years of daily data and ten years of monthly data give exactly the same standard error on μ. More frequent sampling improves σ̂, not μ̂.

Width inflation from μ-error alone, √(1 + T/N):

| Horizon T | N = 5 y | N = 10 y | N = 20 y | N = 50 y |
|---:|---:|---:|---:|---:|
| 1 y | ×1.095 | ×1.049 | ×1.025 | ×1.010 |
| 2 y | ×1.183 | **×1.095** | ×1.049 | ×1.020 |
| 3 y | ×1.265 | ×1.140 | ×1.072 | ×1.030 |
| 5 y | ×1.414 | **×1.225** | ×1.118 | ×1.049 |
| 10 y | ×1.732 | ×1.414 | ×1.225 | ×1.095 |
| 30 y | ×2.646 | ×2.000 | ×1.581 | ×1.265 |

**Direct answer to the question "at 2-year horizons, is parameter uncertainty larger than path uncertainty?"** — No. In *variance* terms it is T/N = 2/10 = **20% of** path uncertainty with Condor's default 10-year window; in *band-width* terms it adds **~10%**. It reaches parity only at T = N (a 10-year forecast from a 10-year window). At 5 years it is 50% of path variance, +22% width.

**But that understates its importance, for three reasons:**

1. **The centre moves, not just the width.** Measured on SPY 2016–2026: μ̂ = 14.26%/yr, σ̂ = 18.01%/yr, SE(μ̂) = σ̂/√10 = **5.70 pp/yr**. A 95% confidence interval on the annual expected return is roughly **2.9% to 25.6%**. The median line of the fan chart is drawn at a number we know only to ±11 pp. A user reading "median 2-year wealth = 1.33×" is reading a number whose own confidence interval spans roughly 1.06× to 1.66×. The band width barely moves; the *location* of the whole fan is what's uncertain.
2. **N is effectively smaller than the calendar window.** Structural breaks, business-model changes and regime shifts mean the last 10 years of AAPL are not 10 years of draws from one distribution. Practitioners who take estimation error seriously use an *effective* N smaller than the nominal one, or a prior.
3. **Compounding bias.** Compounding at the arithmetic mean over a long horizon is both upward-biased and inefficient — Jacquier, Kane & Marcus (2005) show the unbiased long-horizon estimator penalizes the annual compounding rate as T/N grows, roughly weighting the arithmetic mean by (1 − T/N) and the geometric mean by T/N. Condor's default `basis="arithmetic"` is fine for a one-period frontier but is the *wrong* input for a 5-year compounded projection without a correction.

Pástor & Stambaugh (2012), the canonical reference, decompose long-horizon predictive variance into five parts — i.i.d. uncertainty, mean reversion (negative), uncertainty about future expected returns, uncertainty about the current expected return, and estimation risk — and find that once all five are counted, **annualized predictive variance at 30 years is ~1.4× the 1-year variance and at 50 years ~1.9×**, i.e. stocks are *more* volatile per year over long horizons, not less, from a real investor's perspective. Mean reversion contributes about −4.0 (in their units) at 30 years, but estimation risk (+1.6) plus uncertainty about future expected returns (+2.9) more than offsets it.

**Design implication for Condor:** the honest fan chart has two bands (path-only, and path + estimation) and a label on the median line that says what it is conditional on.

---

## 1. Rung 0 — Constant μ/σ: geometric Brownian motion with analytic lognormal bands

**The method.** Assume log returns are i.i.d. Normal(m, s²) daily. Cumulative log return over h days is Normal(h·m, h·s²), so wealth multiple W_h is lognormal and the bands are closed form:

```
quantile_q(W_h) = exp( h·m + z_q · s·√h )
median(W_h)     = exp( h·m )
mean(W_h)       = exp( h·m + h·s²/2 )
```

For a portfolio: m and s come from the portfolio's own return series, or equivalently from wᵀμ and √(wᵀΣw) — Condor already has both (`Portfolio.expected_return`, `Portfolio.dispersion`, `Portfolio.returns`). Note the arithmetic/geometric subtlety: `stats.expected_annual(..., basis="arithmetic")` returns 252·mean(r); for a *relative*-return series the drift of the log-wealth process is approximately μ − σ²/2, and using μ directly overstates median wealth by exp(σ²T/2) — for σ=18%, T=2 that is a **3.3%** overstatement of the median, and for a 30% vol stock over 5 years, **25%**.

**What uncertainty it captures.** Path only. Zero parameter uncertainty, zero model uncertainty.

**What it gets wrong.**
- **Fat tails.** Daily returns are leptokurtic (SPY 2016–2026 kurtosis ≫ 3). At *aggregated* 2-year horizons the CLT largely rescues you — 504 sums of anything with finite variance is close to normal — so this matters much less at 2 years than at 1 day. Measured: 95% 2-year band from analytic GBM on SPY = [0.813×, 2.200×]; from an i.i.d. bootstrap of the actual daily returns = [0.802×, 2.186×]. **The difference is under 2%.** Fat tails are a red herring at multi-year horizons for a diversified portfolio; they matter for a single volatile name and for the 1-month end of the chart.
- **Volatility clustering.** Ignored — see Rung 4; also mostly washes out (Rung 4 quantifies this).
- **Parameter error.** Ignored — this is the real omission (Section 0).
- **Skew / crash risk.** The lognormal is right-skewed in wealth but has no jump component; a 2008-style path is under-represented.

**Data needed.** Daily closes alone: yes, entirely sufficient.

**Packages.** `numpy`, `scipy.stats.lognorm`. Nothing else. Already in the venv.

**Effort.** **S** — about 30 lines, and it doubles as the closed-form verification target for every simulated rung (exactly the "closed form / hand case" test that `CLAUDE.md` requires).

**Interactive?** Instant (microseconds — it's a formula). Simulated GBM at 10 000 paths × 504 days: **180 ms** measured; 50 000 paths: 990 ms.

**Verdict.** Build it. Not as the product, but as the *analytic backbone*: the thing the Monte Carlo must agree with, and the thing that makes the maths in the "technical details" panel explainable.

---

## 2. Rung 1 — I.I.D. bootstrap of historical daily returns

**The method.** Sample daily portfolio returns with replacement, 504 draws per path, compound. No distributional assumption.

**What it captures.** Path uncertainty, with the *empirical* marginal distribution — real skew, real kurtosis, real fat left tail. Still no parameter uncertainty (the bootstrap resamples the sample, so it is centred on μ̂ and inherits its error silently). Still no serial dependence.

**Honest assessment.** As measured above, at 2-year horizons i.i.d. bootstrap and GBM give **nearly identical** bands. Its real value is (a) it removes the "you assumed normal returns" objection at zero cost, (b) it produces *paths*, which look right and let you show drawdown statistics, (c) it is trivially explainable to a retail user ("we shuffled the last 10 years of your portfolio's actual daily moves").

**Data needed.** Daily closes. One caveat: bootstrapping the *portfolio* return series (weights fixed, `Portfolio.returns`) is a daily-rebalanced portfolio; bootstrapping asset returns jointly (resample whole rows to preserve cross-sectional correlation) and then applying weights is the same thing if rebalanced daily. If you want buy-and-hold drift, you must simulate asset paths and let weights drift. **Resample rows, never columns independently** — independent per-asset resampling destroys correlation and will produce absurdly narrow bands for a multi-asset portfolio.

**Packages.** `numpy` (`rng.integers`) — 5 lines. Or `arch.bootstrap.IIDBootstrap` if you want the same API as the block variants.

**Effort.** **S**.

**Interactive?** 10 000 paths × 504 days: **139 ms** measured.

**Verdict.** Build it, as the same engine function as Rung 2 with block length 1.

---

## 3. Rung 2 — Block / stationary bootstrap

**The method.** Resample contiguous *blocks* of returns rather than single days, so volatility clustering, momentum/reversal and (for multi-asset) contemporaneous correlation survive. Three variants:
- **Moving-block bootstrap** (Künsch 1989) — fixed-length blocks, non-stationary output.
- **Circular block bootstrap** — wraps around, so every observation is equally likely.
- **Stationary bootstrap** (Politis & Romano 1994) — block lengths drawn Geometric(p), expected length 1/p; the resampled series is stationary. This is the standard choice.

**Choosing the block length.** The automatic rule is Politis & White (2004), corrected by Patton, Politis & White (2009), available as `arch.bootstrap.optimal_block_length(x)` which returns `b_sb` (stationary) and `b_cb` (circular). It picks a lag-window bandwidth M from the first lag beyond which k_n = max(5, log₁₀ n) consecutive autocorrelations all fall inside a ±2√(log₁₀ n / n) band, then sets b ∝ (2ĝ²/D)^{1/3} n^{1/3}. Reported accuracy is 90–110% of the true optimum in simulation.

**A crucial practical trap, measured on Condor's cache.** I implemented Patton–Politis–White and ran it on the cached 10-year daily log-return series:

| Ticker | PW block on `r` | PW block on `\|r\|` | PW block on `r²` |
|---|---:|---:|---:|
| SPY | 5.8 d | 81.3 d | 55.7 d |
| AAPL | 3.4 d | 81.0 d | 59.7 d |
| GLD | 0.8 d | 86.6 d | 41.8 d |
| JNJ | 3.6 d | 58.1 d | 49.6 d |

Because daily *returns* are almost serially uncorrelated (measured SPY: ρ₁ = −0.132, ρ₅ = +0.047, |ρ| < 0.04 beyond lag 10) while *absolute* returns are strongly persistent (SPY: ρ₁ = 0.36, ρ₂₀ = 0.19, ρ₄₀ = 0.09, dying out around lag 60), **the automatic rule applied to returns tells you to use ~1-week blocks, which throws away all the volatility clustering you wanted the block bootstrap for.** If the goal is realistic *paths* (drawdown sequences, "a bad two years looks like this"), run the selection on |r| and use blocks of roughly one to three months. If the goal is a correct *variance*, the automatic rule on `r` is the technically right answer.

**A second, more serious trap — block bootstrap can silently narrow your bands.** Measured, 20 000 paths, 2-year horizon, 95% band width of the terminal wealth multiple:

| Ticker | realized VR(2y)† | i.i.d. | SB 21 d | SB 63 d | SB 126 d | SB63 / i.i.d. |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 0.061 | 1.370 | 1.139 | 0.977 | 0.892 | **0.72** |
| MSFT | 0.279 | 2.650 | 2.020 | 1.836 | 1.721 | **0.70** |
| AAPL | 0.367 | 2.933 | 2.656 | 2.414 | 2.310 | 0.84 |
| JNJ | 0.053 | 1.350 | 1.181 | 1.064 | 1.050 | 0.80 |
| GLD | 1.792 | 1.152 | 1.102 | 1.135 | 1.195 | 0.99 |
| XOM | 2.367 | 2.133 | 2.122 | 2.154 | 2.088 | 0.99 |

†VR(2y) = variance of non-overlapping 2-year sums ÷ (504 × daily variance), computed from **m = 4** non-overlapping blocks. That "4" is the whole problem: the estimate is pure noise, and it ranges from 0.05 to 2.37 across six tickers over the same calendar decade.

The block bootstrap faithfully reproduces whatever long-horizon mean reversion happens to be in the sample — and over a 10-year window that quantity is estimated from a handful of independent observations. On SPY it produces **28% narrower** 2-year bands than i.i.d., which is not a discovery about markets; it is an artifact of a bull-market decade in which every drawdown was recovered. **Presenting that as the honest band would be the opposite of honest.**

**What it captures.** Path uncertainty *with* serial dependence — genuinely better path realism, genuinely unreliable long-horizon variance from short samples.

**Data needed.** Daily closes. Works best with ≥20 years; 10 years is marginal for anything beyond ~1-year horizons.

**Packages.** `arch.bootstrap.StationaryBootstrap` / `CircularBlockBootstrap` / `MovingBlockBootstrap` / `optimal_block_length`. **arch 8.0.0** (Kevin Sheppard, Oxford) requires Python ≥3.10, is explicitly pandas-3 and numpy-2 ready as of 8.0, and is the de-facto standard financial-econometrics package in Python. It drops into Condor's venv cleanly. A hand-rolled vectorized stationary bootstrap is also ~15 lines and runs at **196 ms** for 10 000 × 504 (measured) — faster than driving `arch`'s generator-based API path-by-path, and it is the shape ARCHITECTURE.md wants (`bootstrap_paths(returns, horizon_days, n_paths, block, seed)`).

**Effort.** **S–M** (S if hand-rolled numpy; M if you also implement/import block-length selection and expose it).

**Interactive?** Yes, ~200 ms at 10 000 paths.

**Verdict.** Build it, with a **fixed, documented, disclosed** expected block length (I'd use ~21 trading days as a defensible compromise: it captures the bulk of the vol-clustering autocorrelation without letting a 4-observation mean-reversion estimate collapse the bands), and **do not** let the block bootstrap be the only band the user sees.

---

## 4. Rung 3 — Parameter / estimation uncertainty (the rung that matters most)

This is not a separate simulation engine — it's an *overlay* that any of Rungs 0–2 can carry, and it is the single highest-value addition to a Condor fan chart.

### 4a. The simplest honest version: draw μ per path

```python
# per path p:  mu_p ~ Normal(mu_hat, sigma_hat^2 / N_obs)   [daily units]
# then simulate the path with mu_p as the drift
```

This is a frequentist "predictive" distribution, and for i.i.d. normal returns with a diffuse prior it coincides with the Bayesian posterior predictive up to a t-vs-normal correction. Cost: one extra `rng.standard_normal(n)` — **zero measurable runtime**.

Measured on SPY (μ̂ = 14.26%/yr, σ̂ = 18.01%/yr, N = 10 y, 20 000 paths, 2-year wealth multiple):

| | 2.5% | 17.5% | median | 82.5% | 97.5% | 95% width | 65% width |
|---|---:|---:|---:|---:|---:|---:|---:|
| GBM, path only | 0.813 | 1.049 | 1.326 | 1.689 | 2.200 | 1.387 | 0.640 |
| GBM + μ uncertainty | **0.772** | 1.021 | 1.334 | 1.731 | **2.331** | 1.559 | 0.710 |
| Stationary bootstrap 63 d | 0.886 | 1.121 | 1.345 | 1.576 | 1.866 | 0.980 | 0.455 |
| SB 63 d + μ uncertainty | 0.842 | 1.087 | 1.342 | 1.631 | 2.008 | 1.166 | 0.544 |

The μ overlay widens the 95% band by **+12.4%** and the 65% band by **+10.9%** — matching the √(1 + T/N) = 1.095 prediction closely (slightly more because of the lognormal transform). On $10 000 invested: path-only 95% range **$8 130 – $22 000**; with estimation error **$7 720 – $23 310**.

### 4b. Also draw Σ (usually second-order, but cheap)

Under normality, the sample covariance follows a Wishart; the natural conjugate draw is Σ ~ Inverse-Wishart(ν = N_obs − 1, scale = N_obs·Σ̂). For a single-asset/portfolio σ, the relative standard error of σ̂ is ≈ 1/√(2·N_obs) — with 2 512 daily observations, **1.4%**. Negligible next to μ's 40% relative error. **Skip Σ uncertainty for the fan chart**; it matters for the *frontier*, not the forecast.

The caveat: 1/√(2n) is the i.i.d.-normal formula. With volatility clustering the effective sample is far smaller — the SPY |r| autocorrelation implies an effective n perhaps 5–10× smaller, so ~3–5% relative error on σ̂. Still second-order.

### 4c. Resampling μ/Σ end-to-end (Michaud-style)

Michaud's resampled efficiency draws (μ*, Σ*) from the sampling distribution of the estimates, re-optimizes, and averages. It is the "right" way to propagate estimation error through an *optimizer*. For a fan chart where the weights are already fixed by the user, the simpler 4a overlay does the same job. Worth noting: the out-of-sample evidence for resampled efficiency is mixed — Michaud (1998) reports Sharpe improvements in simulation; Fletcher & Hillier (2001) could not confirm systematic out-of-sample gains. Same story for Jorion's Bayes–Stein: Chopra, Hensel & Turner (1993) and Jorion (1985, 1991) find it superior to plain MV, while Fletcher (1997) and Grauer & Hakansson (1995) do not.

**Relevance to Condor:** shrinkage is a *frontier* feature (BACKLOG already has Black-Litterman), not a forecaster feature. The forecaster should honour whatever μ the AssetSet produced and add the uncertainty band around it.

### 4d. Full Bayesian predictive distribution

The textbook version: put a prior on (μ, Σ), get the posterior, integrate the predictive distribution over the posterior. For the i.i.d. normal case this is analytic (multivariate-t predictive) and needs no MCMC. For anything richer (regime switching, stochastic vol, predictors), you need PyMC. See Rung 6.

**What uncertainty each variant captures:** parameter uncertainty in μ (dominant), in Σ (minor). *Not* model uncertainty — a wrong window is still a wrong window; drawing μ from N(μ̂, σ̂²/N) assumes the true μ is stable and centred on μ̂.

**Data needed.** Nothing new. Only the count of observations and the calendar span.

**Packages.** `numpy`. Optionally `scipy.stats.invwishart`, `scipy.stats.t`.

**Effort.** **S.** Perhaps 15 lines in `condor/forecast.py`, plus a test asserting the simulated band width matches √(1 + T/N) × the path-only width to within Monte-Carlo error.

**Interactive?** Free.

**Verdict.** **Build this first, alongside Rung 0.** It is the cheapest rung on the ladder and the one that changes what the user believes. Nearly every consumer projection tool omits it. Pfau & Young's critique of Monte Carlo retirement planning is precisely this: two advisors using post-1926 vs post-2000 calibration windows can both report "80% success" while recommending materially different allocations, because the probability score is dominated by a capital-market assumption nobody put an error bar on.

---

## 5. Rung 4 — Volatility dynamics: EWMA, GARCH(1,1)/GJR, HAR, and FHS

**The models.**
- **EWMA / RiskMetrics**: h_t = λh_{t−1} + (1−λ)r²_{t−1}, λ = 0.94 daily. No mean reversion — an IGARCH special case, so the h-step forecast is flat at today's level forever. **Wrong for long horizons by construction.**
- **GARCH(1,1)**: h_t = ω + αr²_{t−1} + βh_{t−1}. Persistence λ = α + β; long-run variance σ²_LR = ω/(1−λ). The h-step forecast is E[h_{t+h}] = σ²_LR + λ^h(h_t − σ²_LR).
- **GJR-GARCH / TARCH**: adds a leverage term (negative returns raise volatility more). Fits equities materially better than plain GARCH.
- **HAR** (Corsi 2009): regress realized volatility on daily/weekly/monthly RV components. Captures long memory better than GARCH and is the workhorse of the realized-volatility literature — but it wants intraday data to construct RV. From daily closes alone you can use squared daily returns or Garman–Klass/Yang–Zhang range estimators, which is a meaningful downgrade.
- **FHS** (Barone-Adesi, Giannopoulos & Vosper 1999): fit a GARCH-type model, standardize residuals z_t = r_t/√h_t, then simulate forward by bootstrapping from the empirical pool of ẑ. Combines the conditional variance dynamics with the empirical (fat-tailed, skewed) shock distribution. This is the correct way to marry Rungs 2 and 4, and it is the standard for multi-period VaR.

### Does it matter at 1–5 years? Quantitatively, no.

Cumulative variance over T days is Σ E[h_t] = T·σ²_LR + (h₀ − σ²_LR)·(1 − λ^T)/(1 − λ). The second term is **bounded** by (h₀ − σ²_LR)/(1 − λ) — at most `1/(1−λ)` extra days' worth of variance, no matter how long the horizon. So today's volatility state contributes a *fixed number of days* of extra variance, which becomes negligible as T grows.

Half-lives and the resulting SD inflation (computed):

| α+β | half-life | max "extra days" 1/(1−λ) | SD ratio at 1 m, vol 2× LR | at 1 y | at **2 y** | at 5 y |
|---:|---:|---:|---:|---:|---:|---:|
| 0.94 (EWMA-ish) | 11 d | 17 | ×1.65 | ×1.10 | **×1.05** | ×1.02 |
| 0.97 | 23 d | 33 | ×1.80 | ×1.18 | **×1.10** | ×1.04 |
| 0.98 (typical equity) | 34 d | 50 | ×1.86 | ×1.26 | **×1.14** | ×1.06 |
| 0.99 (high persistence) | 69 d | 100 | ×1.93 | ×1.45 | **×1.26** | ×1.11 |
| 0.995 (near-IGARCH) | 138 d | 200 | ×1.96 | ×1.65 | ×1.45 | ×1.22 |

**Read this as: with typical equity persistence (α+β ≈ 0.98, half-life ~7 weeks), starting from *double* the long-run volatility widens the 2-year band by 14% and the 5-year band by 6%. Starting from half the long-run volatility narrows the 2-year band by ~4%.** For comparison, the μ-uncertainty overlay (Rung 3, free) widens the 2-year band by 10% and the 5-year band by 22%. **GARCH buys less than parameter uncertainty at every horizon Condor cares about, and costs 10× more to build.**

The exception is the short end: at a 1-month horizon, the conditional variance state changes the band by ×1.65–1.96 — nearly a doubling. If Condor's fan chart starts at "today" and the first visible tick is a month out, GARCH visibly improves the *near* part of the cone. Whether that's worth it is a UI judgement.

The other exception is **March-2020-style conditions**. If a user opens the app the week after a crash, the unconditional-variance fan is genuinely too narrow for the next quarter. A "current market conditions" toggle that switches the near end of the cone to a GARCH-filtered start is a legitimate feature — just not a 1–5-year one.

**What it captures.** Path uncertainty, refined: conditional heteroskedasticity, and (with FHS) the empirical shock distribution and leverage effect. Nothing about parameters.

**Data needed.** Daily closes suffice for GARCH/GJR/EWMA/FHS. HAR properly wants intraday; from daily data use range-based estimators (needs OHLC, which `PriceStore` currently does not keep — it stores `close`/`adj_close`).

**Packages.** `arch` 8.0.0 — `arch_model(returns, vol="GARCH"/"EGARCH", p=1, o=1, q=1, dist="skewt")`, plus `.forecast(horizon=..., method="simulation"/"bootstrap", simulations=...)` which does FHS natively via `method="bootstrap"`. Very mature, well documented, well tested. A GARCH(1,1) fit on 2 500 observations takes ~50–300 ms. A hand-vectorized FHS path simulation (loop over 504 days, vectorized across 10 000 paths) measured at **183 ms** — arch's own simulation API is slower for this shape, so if you build it, hand-vectorize the recursion using arch only for the fit.

**Effort.** **M.** Fit + parameter validation + a sensible fallback when the fit fails to converge (it will, on short/illiquid series) + a "which α+β did we get" disclosure. Fitting GARCH per asset and aggregating to a portfolio requires a multivariate model (DCC — not in `arch`; `mgarch` packages in Python are immature) or fitting GARCH directly to the *portfolio* return series, which is the pragmatic choice and is what Condor should do.

**Interactive?** Yes: fit ~0.2 s + simulate ~0.2 s. But cache the fit per (portfolio, window).

**Verdict.** **Defer.** Rung D at best. Build it only if you add a short-horizon (1–12 month) view or a "current conditions" toggle. At 2–5 years the numbers above say it's a rounding error next to the μ problem.

---

## 6. Rung 5 — Regime-switching (Markov) models

**The method.** Hamilton (1989): returns are drawn from one of K states with state-specific (μ_k, σ_k), and the state follows a Markov chain with transition matrix P. Simulating forward means simulating the chain and the returns jointly, starting from the filtered/smoothed current-state probabilities.

**Does it improve long-horizon density forecasts in practice?** The honest answer is *sometimes, and mostly for volatility, and mostly at horizons under a year*.

- Guidolin & Timmermann (2007, *JEDC*; 2008, *RFS*) find **four** regimes are needed to capture the joint distribution of stock and bond returns (crash / slow growth / bull / recovery), that optimal allocations differ sharply across states, and that out-of-sample experiments "confirm the economic importance of accounting for the presence of regimes." Notably, they find the *horizon effect flips sign by regime*: in the crash state a buy-and-hold investor holds more equity the longer the horizon; in the bull state, less.
- For volatility, Markov-switching HAR models with time-varying transition probabilities dominate at weekly/monthly horizons; regime-switching approaches improve S&P 500 volatility forecasting.
- On the retirement-planning side, Kitces' Brier-score evaluation reports that Historical and Regime-Based Monte Carlo models score ~25% better (lower Brier) than Traditional Monte Carlo.

**But:** the *long-run* distribution of a stationary Markov chain is its ergodic distribution, and simulating T = 504 days of a chain with typical monthly-scale persistence means you've visited the ergodic mixture many times. Regime switching therefore does two useful things at long horizons — it produces the right *unconditional* fat tails and negative skew (mixture of normals), and it correctly conditions the *near* end on today's state — and one thing it does badly: it introduces K×(K+1) more parameters estimated from the same 10 years, so it *increases* parameter uncertainty considerably while the model is fit by maximum likelihood that ignores that uncertainty. Label-switching and non-identification make MLE fits on 10-year windows unstable.

**What it captures.** Path uncertainty with state-dependent mean *and* variance (so: skew, fat tails, and clustering, all at once), plus the conditional "we are currently in a bad state" information. Adds *more* unacknowledged parameter uncertainty.

**Data needed.** Daily closes work; monthly is more common and more stable for regime fitting on 10–20-year samples. Fitting a 2-state model to 2 500 daily returns is feasible; 4 states is not, from 10 years of one series.

**Packages.** `statsmodels.tsa.regime_switching.MarkovRegression` and `MarkovAutoregression` — already in the venv (statsmodels 0.14.6), stable, supports switching variance and time-varying transition probabilities via `exog_tvtp`. Mature but thin: no built-in simulation-from-filtered-state helper, so you write the forward simulation yourself (~30 lines). `hmmlearn` is an alternative but less econometrically oriented.

**Effort.** **M–L.** Fit stability, state labelling (which state is "the bad one"), starting-state probabilities, and the UI question of what to *say* about it all cost more than the code.

**Interactive?** Fit: 1–10 s on daily data (EM iterations) — **needs precompute/caching**. Simulation from a fitted model: fast.

**Verdict.** **Skip for now.** A 2-state Gaussian mixture gives you 80% of the tail-shape benefit at 5% of the cost, and the stationary bootstrap gives you the same thing non-parametrically. Revisit if Condor ever adds a "market conditions" / "regime" concept to the UI, where the *state estimate itself* is the product.

---

## 7. Rung 6 — Bayesian approaches

### 7a. Black–Litterman as a prior on μ

Black & Litterman (1992) reverse-engineer an equilibrium μ from market-cap weights and a risk-aversion parameter, then blend it with the user's views weighted by stated confidence. Its relevance to the *forecaster* is indirect but real: **it is a principled way to stop the fan chart from being centred on a 10-year bull-market sample mean.** SPY's μ̂ of 14.26%/yr from 2016–2026 is not a defensible 2-year expectation; a CAPM/equilibrium anchor of, say, 7–8% is.

The generalizable idea: **shrink μ̂ toward a long-run anchor with weight determined by the ratio of prior variance to sampling variance.** With SE(μ̂) = 5.7 pp and a prior of, say, 8% ± 3 pp, the posterior mean lands near 9.5% — closer to defensible, and with a posterior SD of ~2.6 pp instead of 5.7 pp. The fan chart then centres somewhere honest *and* narrows slightly, because you brought in information.

**Packages.** `pypfopt.black_litterman.BlackLittermanModel` — PyPortfolioOpt 1.6.0 is installed; the BL module supports Idzorek's confidence method (`omega="idzorek"`). Mature, well documented. Note the project moved to the `PyPortfolio/PyPortfolioOpt` org; maintenance is community-driven and slower than it was.

**Effort.** **M** (mostly UI: where does the anchor come from, what does the user type?). It is already a BACKLOG item in its own right.

### 7b. Full posterior predictive simulation (PyMC)

Write the generative model, sample the posterior over (μ, σ, and whatever else), then draw future paths from the posterior predictive. This is the *correct* general framework — it makes parameter uncertainty automatic rather than bolted on, handles hierarchical structure (shrink each asset's μ toward a sector/market μ), and handles non-conjugate models (Student-t returns, stochastic volatility, regime switching with priors on P).

**Reality check for Condor:** for the i.i.d.-normal model, the posterior predictive is available *in closed form* (a Student-t predictive for the cumulative return with N−1 degrees of freedom) and requires no MCMC. Rung 3's `μ_p ~ N(μ̂, σ̂²/N)` overlay **is** the posterior predictive under a diffuse prior, up to swapping normal for t. Bringing in PyMC buys nothing until the model itself is non-conjugate.

**Packages.** PyMC **6.3.1** — mature, actively developed, but **requires Python ≥ 3.12** and Condor's venv is on **3.11.1**. It also pulls in PyTensor + ArviZ, which is a heavy dependency for a Django app. Sampling a 2-parameter model on 2 500 observations takes seconds; a stochastic-volatility model takes minutes.

**Effort.** **L**, plus a Python upgrade, plus a precompute/queue architecture.

**Interactive?** No. Precompute only.

**Verdict.** **Use the closed-form/normal-approximation Bayesian result now (Rung 3); keep PyMC out of the dependency tree** until there's a model that genuinely needs it. Do adopt a *prior on μ* (7a) as the third rung — that is where the honesty payoff is.

### 7c. Shrinkage generally

Ledoit–Wolf for Σ is already in Condor via PyPortfolioOpt (`stats.py` uses it for the "normal" method) — good. For μ, Jorion's Bayes–Stein shrinks toward the minimum-variance portfolio's return. Evidence is mixed (Section 4c). For the *forecaster*, a simple, explainable shrink toward a stated long-run assumption beats Bayes–Stein on interpretability, which is what this app trades on.

---

## 8. Rung 7 — Modern ML / SOTA

### 8a. Quantile regression and gradient boosting with pinball loss

Fit q̂_τ(y | x) directly for τ ∈ {0.025, 0.175, 0.5, 0.825, 0.975} using `sklearn.ensemble.GradientBoostingRegressor(loss="quantile", alpha=τ)`, LightGBM's `objective="quantile"`, or `statsmodels.QuantReg`. Elegant, cheap, and completely inapplicable here — because the target is a **2-year-ahead cumulative return**, and with 10 years of history you have **5 non-overlapping training examples**. Overlapping windows give ~2 000 examples that are 99.6% redundant; a boosted tree will memorize them and report a spectacular in-sample pinball loss that means nothing. This is the Valkanov/Stambaugh overlapping-long-horizon-regression problem in its most naive form.

Even at a *monthly* target, the ceiling is low: Gu, Kelly & Xiu (2020) — the benchmark ML-in-asset-pricing paper, RFS — set what was then a new standard for out-of-sample return-prediction R², and that standard is fractions of a percent per month for the cross-section, achieved with hundreds of firm characteristics and macro predictors. Condor has daily closes and nothing else.

**Verdict:** no.

### 8b. Conformal prediction for time series (EnbPI, ACI, AgACI)

Conformal prediction gives distribution-free, finite-sample coverage guarantees for exchangeable data, and the time-series variants relax exchangeability: **EnbPI** (Xu & Xie, ICML 2021 / TPAMI) uses ensemble/block-bootstrap out-of-bag residuals; **ACI** (Gibbs & Candès, NeurIPS 2021) adapts the miscoverage level online so realized coverage converges to the target; **AgACI** (Zaffran et al., ICML 2022) aggregates over the ACI step size. 2025–2026 work extends these to multi-step horizons (AcMCP and others), explicitly noting that most conformal-for-time-series work is single-step and multi-step is comparatively under-developed.

This is genuinely the most attractive of the ML options *in principle* — it is the only family whose selling point is exactly what Condor wants, honest coverage. But:

- **The calibration set problem.** ACI's guarantee is asymptotic in the number of *sequential feedback rounds*. At a 2-year horizon you get one feedback signal every two years. There is no online adaptation to be had.
- **It calibrates the wrong thing.** Conformal corrects a predictor's *residual* quantiles based on observed residuals. At 2 years, the residuals are dominated by the μ error — which is exactly the quantity conformal would need decades of independent observations to calibrate.
- Applying conformal to *daily* residuals and then aggregating to 2 years reintroduces every i.i.d. assumption conformal was supposed to avoid.

**Packages.** MAPIE **1.5.0** (5 Aug 2026, scikit-learn-contrib, Python ≥3.10, sklearn ≥1.4) with `TimeSeriesRegressor` implementing EnbPI with block-bootstrap resampling. Genuinely mature and well maintained. The reference EnbPI implementation lives at `hamrel-cxu/EnbPI`.

**Verdict:** the package is fine; the horizon is wrong. **Skip.** Reconsider only if Condor ever adds a 1-day-to-1-month risk view with daily feedback, where ACI would shine.

### 8c. Deep probabilistic models (DeepAR-style)

DeepAR (Salinas et al. 2020) and the GluonTS family produce Monte Carlo sample paths from an autoregressive RNN with a parametric output distribution. GluonTS is at **0.17.0**, Python ≥3.10 <3.15, PyTorch-based (`torch >= 2.10`), production-stable — a serious ~2 GB dependency for a Django app serving five users.

DeepAR's strength is *cross-series* learning across thousands of related series (retail demand, energy load). Condor has one portfolio and a handful of tickers. There is no panel to learn from, no covariates, and 2 500 observations.

### 8d. Time-series foundation models (Chronos, TimesFM, Moirai)

The 2026 evidence is unusually clear and unusually negative. A June 2026 benchmark of Chronos, Chronos-2, TimesFM-2.5 and Moirai-2.0 on five large-cap US equities found that although Moirai-2.0 and TimesFM-2.5 rank best on average, **gains over the random-walk benchmark are "small and sparse," and a one-sided Diebold–Mariano test rejects equal-or-inferior accuracy in only 2 of the tested cases.** An earlier 2025 study found off-the-shelf TSFMs perform *weakly* in zero-shot forecasting of daily excess returns, underperforming CatBoost/LightGBM ensembles. The reviewers' summary — these models "reduce development costs rather than deliver breakthrough predictive performance in financial markets" — is the fair verdict.

Applied to a **2-year** horizon, where these models are typically evaluated at horizons of tens of steps and the finance evidence is for *daily* forecasting, the case is weaker still.

### Honest verdict on the whole ML tier

**At 1–5 year horizons for a buy-and-hold retail portfolio, none of these beat the simple ladder, and most of them can't even be honestly *trained*.** The binding constraint is not model capacity — it is that a 2-year forecast has, at most, `history_years / 2` independent observations to learn from. With 10 years of data that is five. No architecture recovers information that isn't in the sample. Goyal, Welch & Zafirov (2024, *RFS*) reinforce this at the market level: of 29 predictors published *after* the original 2008 critique, more than a third are no longer significant even in-sample, and half of the survivors fail out-of-sample. The equity-premium prediction literature has spent forty years failing to beat a rolling historical mean out of sample.

The correct place to spend engineering effort is **quantifying how badly we know μ**, not on better μ.

---

## 9. The aggregation question: daily model → 2-year horizon, or model at 2 years directly?

Three options:

**(a) Model daily, compound to T.** What everything above does. Uses all 2 512 observations for σ̂. Assumes (approximately) i.i.d. or block-dependent daily returns, so long-horizon variance ≈ σ²T — variance ratio pinned at 1 by construction (or nudged by the block length).

**(b) Model at monthly/annual frequency directly.** Fewer, cleaner observations; captures whatever mean reversion exists at that frequency. From 10 years you get 120 monthly or 10 annual returns. Condor's `stats.py` already supports this via `timeframe="M"` with `samp_int=20` to de-overlap.

**(c) Model the T-horizon return directly.** With 10 years of data and T = 2, this is **five** non-overlapping observations. Not a method; a joke.

**Should bands grow slower than √t?** The literature says: probably a little, but you cannot measure it, and the correction is smaller than the parameter uncertainty you'd be ignoring.

- Fama & French (1988) and Poterba & Summers (1988) documented negative long-horizon autocorrelation, with F&F attributing 25–40% of 3–5-year return variation to a mean-reverting component.
- Richardson & Stock (1989), Richardson (1993) and Richardson & Smith (1991) showed the evidence largely evaporates once small-sample bias in overlapping variance ratios is corrected. Poterba & Summers themselves conceded that variance-ratio tests "have little power … even with data spanning a sixty-year period" — less than a one-in-four chance of rejecting the random walk against economically interesting alternatives.
- Pástor & Stambaugh (2012) close the loop: mean reversion *is* there and *is* negative, but once you count estimation risk and uncertainty about future expected returns, **net annualized long-horizon variance exceeds the 1-year variance** (×1.4 at 30 years, ×1.9 at 50).

Condor's own data makes the powerlessness vivid. Measured non-overlapping variance ratios from the 10-year cache (m = 4 blocks at 2 years):

| Ticker | VR(1 w) | VR(1 m) | VR(3 m) | VR(6 m) | VR(1 y) | VR(2 y) |
|---|---:|---:|---:|---:|---:|---:|
| SPY | 0.98 | 0.75 | 0.33 | 0.22 | 0.38 | **0.06** |
| AAPL | 0.93 | 0.91 | 0.68 | 0.59 | 0.73 | **0.37** |
| GLD | 0.99 | 1.04 | 0.89 | 1.21 | 1.00 | **1.79** |
| JNJ | 0.93 | 1.07 | 0.69 | 0.49 | 0.19 | **0.05** |
| XOM | — | — | — | — | — | **2.37** |
| MSFT | — | — | — | — | — | **0.28** |

Ranging from 0.05 to 2.37 for the same asset class over the same decade, from four observations each. Any band-narrowing rule fitted to these numbers is fitting noise.

**Recommendation: model daily (option a), let bands grow as √t, and do not apply a mean-reversion discount.** Note it in the technical panel as a known conservatism. If you ever want to *test* the assumption, the right instrument is `arch.unitroot.VarianceRatio` on a much longer series (Shiller's monthly S&P back to 1871, or Ken French's daily market factor back to 1926) — not the user's 10-year ticker window.

One aggregation nuance worth honouring: **use daily data for σ̂ and the longest defensible calendar span for μ̂**, because they have different sufficient statistics (Merton). Condor could legitimately estimate σ from a 3-year daily window (recent, plenty of observations) and μ from a 15–20-year window or a prior (span is all that matters). Making the two windows independently configurable is a genuinely well-motivated feature that almost no consumer tool offers.

---

## 10. Comparison table

| # | Method | Uncertainty captured | Data needed | Python packages (maturity) | Effort | Interactive? (10k paths, 2 y) |
|---|---|---|---|---|---|---|
| 0 | **Analytic GBM lognormal** | path only | daily closes | numpy, scipy (trivial) | **S** | ✅ instant (closed form) |
| 1 | **Monte Carlo GBM** | path only | daily closes | numpy | **S** | ✅ 180 ms |
| 2 | **I.I.D. bootstrap** | path + empirical tails | daily closes | numpy; `arch.bootstrap.IIDBootstrap` (arch 8.0.0, mature) | **S** | ✅ 139 ms |
| 3 | **Stationary/block bootstrap** | path + tails + serial dependence (⚠ inherits sample's mean reversion) | daily closes, ≥20 y preferred | `arch.bootstrap.StationaryBootstrap`, `optimal_block_length` (mature) | **S–M** | ✅ 196 ms |
| 4 | **Parameter (μ) uncertainty overlay** | **estimation error in μ** — the dominant term | none extra (obs count + span) | numpy | **S** | ✅ free |
| 4b | Σ uncertainty (inverse-Wishart) | estimation error in Σ (≈1.4% rel. — negligible) | none extra | scipy.stats.invwishart | **S** | ✅ free |
| 5 | **EWMA vol** | conditional vol, no mean reversion (wrong for long h) | daily closes | numpy / `arch` | **S** | ✅ |
| 6 | **GARCH(1,1) / GJR** | conditional vol with mean reversion; +14% band at 2 y from 2× vol start | daily closes | `arch` 8.0.0 (very mature, pandas-3 ready) | **M** | ✅ fit 0.2 s + sim 0.2 s (cache the fit) |
| 7 | **FHS (GARCH + bootstrapped ẑ)** | conditional vol **+** empirical shock shape | daily closes | `arch` (`forecast(method="bootstrap")`) or hand-vectorized | **M** | ✅ 183 ms + fit |
| 8 | **HAR** | long-memory vol | wants intraday RV; degraded from daily/OHLC | statsmodels OLS; no canonical pkg | **M** | ✅ |
| 9 | **Markov regime switching** | state-dependent μ and σ; skew/fat tails; current-state conditioning. Adds unpriced parameter risk | daily or monthly closes | `statsmodels.tsa.regime_switching.MarkovRegression` (mature but thin — write your own simulator) | **M–L** | ⚠ fit 1–10 s → precompute |
| 10 | **Black–Litterman prior on μ** | shifts and shrinks the *centre*; reduces μ variance | closes + market caps or a stated anchor | `pypfopt.black_litterman` (1.6.0, mature, community-maintained) | **M** | ✅ |
| 11 | **Full Bayesian posterior predictive** | parameter + model, properly | daily closes | PyMC 6.3.1 (mature; **needs Python ≥3.12**, venv is 3.11) + PyTensor + ArviZ | **L** | ❌ precompute |
| 12 | **Quantile GBM / pinball loss** | conditional quantiles — but only 5 independent 2-y examples exist | daily closes (insufficient) | sklearn, LightGBM (mature) | **M** | ✅ but meaningless |
| 13 | **Conformal (EnbPI / ACI / AgACI)** | distribution-free coverage — needs many sequential feedback rounds | needs decades of independent horizons | MAPIE 1.5.0 `TimeSeriesRegressor` (mature, Aug 2026) | **M** | ✅ but no guarantee at 2 y |
| 14 | **DeepAR / GluonTS** | learned predictive density (needs a panel of series) | far more than Condor has | GluonTS 0.17.0 + torch ≥2.10 (mature, heavy) | **L** | ❌ offline training |
| 15 | **TS foundation models** | zero-shot density; 2026 benchmarks show gains over random walk are "small and sparse" | n/a | Chronos-2, TimesFM-2.5, Moirai-2.0 | **L** | ❌ |

---

## 11. Backtest mode: how to evaluate honestly

The backtest ("project from 2 years ago, compare to what happened") is the most valuable *and* most easily abused part of this feature. Two levels:

**Level 1 — the single-case illustration (what the UI shows).** Refit μ̂/σ̂ on data ending at t₀ = today − 2 y (strictly: `PriceStore` slice ending at t₀, no leakage), draw the fan, overlay the realized path, and report **the percentile the realized outcome landed in**. One observation. Say so: "this is one draw; landing at the 8th percentile once is not evidence the model is wrong."

**Level 2 — the coverage study (what earns the right to ship the bands).** Roll t₀ over many start dates (monthly, over as much history as `PriceStore` holds), and tabulate:

- **PICP / hit rate**: fraction of realized outcomes inside the nominal 65% and 95% bands. Formal test: Kupiec unconditional-coverage LR test.
- **PIT histogram**: transform each realized outcome through its own predictive CDF; under a correct model these are Uniform(0,1). Deviations from flatness name the failure — U-shaped = bands too narrow, hump-shaped = too wide, sloped = biased centre.
- **CRPS** (or pinball loss averaged over a quantile grid, which approximates it) as the headline proper scoring rule, compared across rungs. CRPS is the right single number: it rewards sharpness *subject to* calibration.

**The caveat that must be in the code comments and the docs:** overlapping 2-year windows are ~99.6% correlated. A 20-year history gives ~10 truly independent observations, so a coverage estimate of "63% inside the 65% band" has a standard error of roughly ±15 pp. Report the effective sample size next to the hit rate, or the backtest will be read as validation it cannot provide. This is exactly the difficulty flagged in the fan-chart-communication literature: probabilistic outputs get read as guarantees.

**A concrete prediction to test:** the coverage study should show that path-only bands under-cover (too narrow), and that adding the μ overlay moves the hit rate toward nominal. If it doesn't, that's informative too.

---

## 12. Recommended ladder for Condor

Build **three rungs, in this order.** All three live in `condor/forecast.py` as pure functions, composed by `Portfolio.forecast()` returning a `Forecast` object with `to_dict()`, exactly as `ARCHITECTURE.md`'s worked example lays out.

### Rung A — Analytic GBM + Monte Carlo GBM + **μ-uncertainty overlay** (ship first)

```python
# condor/forecast.py
def lognormal_bands(mu, sigma, horizon_years, levels=(0.65, 0.95)) -> pd.DataFrame
def gbm_paths(mu, sigma, horizon_days, n_paths, mu_se=None, seed=None) -> np.ndarray
def band_quantiles(paths, levels=(0.65, 0.95)) -> pd.DataFrame
def mu_standard_error(returns, annual_factor) -> float   # sigma / sqrt(span_years)
```

- `lognormal_bands` is the closed form and is the verification test target for `gbm_paths(mu_se=None)` — satisfying `CLAUDE.md`'s "engine changes need a closed-form test."
- `mu_se=None` → path-only bands. `mu_se=σ̂/√N` → path + estimation bands. **Both are computed and both are returned in `to_dict()`**, so the UI can draw them together.
- Use the **log-drift correction**: median wealth = exp((μ − σ²/2)·T) when μ is the arithmetic annual return of a relative-return series. Without it the median is overstated by exp(σ²T/2) — 3.3% at σ=18%, T=2 y; 25% for a 30%-vol name at 5 y.
- Cost: ~200 ms for 10 000 paths. Effort: **S**.

### Rung B — Stationary block bootstrap (ship second, same engine signature)

```python
def bootstrap_paths(returns, horizon_days, n_paths, block=21, mu_se=None, seed=None) -> np.ndarray
```

- Fixed default `block=21` trading days, disclosed in the UI. **Do not** auto-select via Politis–White on raw returns — measured, that gives 1–6 days, i.e. i.i.d.
- Its job is **path realism** (drawdown sequences, "what a bad two years looks like", empirical skew) — a much better narrative asset than GBM's smooth cone. Its job is **not** to set the band width; the measured SB63/i.i.d. width ratios of 0.70–0.99 across tickers show that width is sample-noise-driven.
- Guard rail: if the block-bootstrap 95% width comes out narrower than the GBM + μ-uncertainty width, **show the wider one** (or show both and label). Never let a bull-market decade produce the narrowest cone on the page.
- Resample **rows** of the multi-asset return frame, never columns independently.
- Cost: ~200 ms. Effort: **S–M**.

### Rung C — A prior / anchor on μ (ship third)

Not GARCH. The measured numbers say GARCH buys +14% band width at 2 years in the *extreme* case, while the centre of the chart is off by an amount with a ±11 pp confidence interval.

- Minimum viable version: a UI control — "Expected return assumption: **[Historical 14.3%] [Long-run market 8%] [Custom ___]**" — and a corresponding posterior blend when the user picks something between. Redraw the fan live; the user *sees* that the whole chart hinges on this one number. That is the most educational thing the feature can do.
- Fuller version: wire `pypfopt.black_litterman.BlackLittermanModel` (already installed) so the anchor is a CAPM-equilibrium μ from market caps and the user's tilt is a "view." This closes the BACKLOG "Bayesian views / Black-Litterman" item at the same time.
- Effort: **M**, mostly UI.

### Explicitly deferred, with reasons

| Deferred | Why |
|---|---|
| GARCH/GJR/FHS | ×1.05–1.14 on the 2-year band vs ×1.10–1.22 free from the μ overlay. Revisit **only** with a 1–12-month view or a "current market conditions" toggle. |
| HAR | Needs intraday or OHLC; `PriceStore` keeps only close/adj_close. |
| Regime switching | Fit instability on 10-y windows; ergodic mixture washes out by 2 y; adds parameter risk nobody prices. |
| PyMC | Closed-form posterior predictive already covers the conjugate case; PyMC 6.3.1 needs Python ≥3.12 (venv is 3.11) plus PyTensor/ArviZ. |
| Conformal / MAPIE | Guarantee needs many sequential feedback rounds; at 2 y you get one every two years. |
| DeepAR / TSFMs / quantile GBM | Five independent training examples. 2026 benchmarks show foundation models barely beat random walk on *daily* returns. |
| Mean-reversion band narrowing | Condor's own data gives VR(2y) ∈ [0.05, 2.37] across six tickers from 4 observations each. Not measurable. |

### What to show in the UI so the bands are honest

1. **Two nested band sets, differently labelled.** Inner fill: "market randomness" (path-only). Outer, lighter/hatched: "**+ uncertainty in our return estimate**". A legend row for each. This single choice is the whole feature's integrity.
2. **Name what the median assumes.** Not "expected value." Something like: *"Middle line: what happens if your portfolio's next 2 years average the same return as its last 10 (14.3%/yr)."*
3. **Put the estimate's error bar on screen as a number.** *"Estimated return: 14.3%/yr. From 10 years of data, that estimate is good to about ±5.7 pp — the true long-run figure is plausibly anywhere from 3% to 26%."* This is the Merton result, in one sentence a retail user can act on.
4. **Dollars and multiples, not log returns.** "$10,000 → $8,130–$22,000 (95%), $10,490–$16,890 (65%)" with the outer band widening to $7,720–$23,310 once estimate error is on.
5. **Disclose the knobs.** Method (GBM / bootstrap), block length, estimation window, number of paths, seed. Same "technical details" affordance the deck already plans for every concept.
6. **Backtest panel:** the realized path over the historical fan, the realized outcome's percentile, *and* the rolling coverage table with its effective sample size. Never the percentile alone.
7. **Never print a bare "probability of success."** The Kitces/Pfau critique is that a probability score can swing from 83% to 91% on a 0.5 pp change in assumed return. If Condor ever shows a probability of hitting a goal, show it as a *range across return assumptions*, driven by the Rung-C control.
8. **State the model's blind spot in one line.** *"These bands assume the future resembles the past decade in kind, if not in detail. They cannot price a change in what your holdings fundamentally are."*

### Suggested engine API (fits ARCHITECTURE.md unchanged)

```python
# condor/forecast.py  — pure functions over arrays/frames
def mu_standard_error(returns, annual_factor=252) -> float
def lognormal_bands(mu, sigma, horizon_years, mu_se=0.0, levels=(0.65, 0.95)) -> pd.DataFrame
def gbm_paths(mu, sigma, horizon_days, n_paths, mu_se=0.0, seed=None) -> np.ndarray
def bootstrap_paths(returns, horizon_days, n_paths, block=21, mu_se=0.0, seed=None) -> np.ndarray
def band_quantiles(paths, levels=(0.65, 0.95)) -> pd.DataFrame
def coverage(realized, bands) -> dict          # backtest: hit rate, PIT, CRPS

# condor/model.py
class Portfolio:
    def forecast(self, horizon_years=2, n_paths=10_000, method="bootstrap",
                 include_estimate_error=True, seed=None) -> "Forecast": ...

class Forecast:                 # paths (optional), bands, bands_path_only,
                                # mu, sigma, mu_se, method, window, to_dict()
    def backtest(self, as_of) -> "Forecast": ...
```

Ten thousand paths over 504 days is **~0.2 s** in pure numpy — comfortably inside the interactive budget for five users, with no precompute, no queue, and no new heavyweight dependency. `arch` (8.0.0, pandas-3 ready) is the only package worth adding, and only if you want its block-length selection and, later, GARCH.

---

## 13. References

**Estimation error and long-horizon uncertainty**
- Merton, R. C. (1980). "On Estimating the Expected Return on the Market: An Exploratory Investigation." *JFE* 8, 323–361. https://www.nber.org/papers/w0444 · https://www.sciencedirect.com/science/article/abs/pii/0304405X80900070
- Pástor, Ľ. & Stambaugh, R. F. (2012). "Are Stocks Really Less Volatile in the Long Run?" *Journal of Finance* 67(2), 431–478. https://onlinelibrary.wiley.com/doi/full/10.1111/j.1540-6261.2012.01722.x · https://www.nber.org/papers/w14757
- Barberis, N. (2000). "Investing for the Long Run when Returns Are Predictable." *Journal of Finance*. https://nicholasbarberis.github.io/alloc_jnl.pdf
- Jacquier, E., Kane, A. & Marcus, A. J. (2005). "Optimal Estimation of the Risk Premium for the Long Run and Asset Allocation: A Case of Compounded Estimation Risk." *J. Financial Econometrics* 3(1), 37–55. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=821736 · https://people.bu.edu/jacquier/papers/longt.jfec05.pdf
- Jacquier, E. (2012). "Asset Allocation in Finance: A Bayesian Perspective." https://people.bu.edu/jacquier/papers/JP-Smithchap-2012.pdf
- Ostrov, D. & Das, S. "Unrealistic Expectations: The Futility of Precisely Estimating a Stock's Expected Return." https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4662525
- Müller, U. & Watson, M. "Measuring Uncertainty about Long-Run Predictions." https://www.princeton.edu/~umueller/longpred.pdf

**Shrinkage and resampling in portfolio choice**
- Jorion, P. (1986). "Bayes-Stein Estimation for Portfolio Analysis." *JFQA*. https://www.semanticscholar.org/paper/d4a7359fe7495ed332517097be56c312c9834030
- Michaud, R. (1998). *Efficient Asset Management* / "Estimation Error and Portfolio Optimization: A Resampling Solution." https://newfrontieradvisors.com/media/rxbld4hq/estimation-error-and-portfolio-optimization-12-05.pdf
- "Portfolio Choice and Estimation Risk: A Comparison of Bayesian Approaches" (survey of the mixed evidence). https://www.econstor.eu/bitstream/10419/76907/1/wp094.pdf
- Black, F. & Litterman, R. (1992). "Global Portfolio Optimization." *FAJ*. Implementation: https://pyportfolioopt.readthedocs.io/en/latest/BlackLitterman.html

**Bootstrap**
- Politis, D. & Romano, J. (1994). "The Stationary Bootstrap." *JASA*.
- Politis, D. & White, H. (2004). "Automatic Block-Length Selection for the Dependent Bootstrap." *Econometric Reviews* 23(1). https://public.econ.duke.edu/~ap172/Politis_White_2004.pdf
- Patton, A., Politis, D. & White, H. (2009). "Correction to 'Automatic Block-Length Selection for the Dependent Bootstrap'." *Econometric Reviews* 28(4). https://public.econ.duke.edu/~ap172/Patton_Politis_White_2009.pdf
- `arch.bootstrap.optimal_block_length` docs: https://arch.readthedocs.io/en/latest/bootstrap/generated/arch.bootstrap.optimal_block_length.html

**Volatility dynamics**
- Barone-Adesi, G., Giannopoulos, K. & Vosper, L. (1999). Filtered Historical Simulation. Overview: https://www.mathworks.com/help/econ/using-bootstrapping-and-filtered-historical-simulation-to-evaluate-market-risk.html
- "Comparative Evaluation of VaR Models: Historical Simulation, GARCH-Based Monte Carlo, and Filtered Historical Simulation" (2025). https://arxiv.org/pdf/2505.05646
- Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." *J. Financial Econometrics* 7(2). https://www.researchgate.net/publication/227464926
- NYU V-Lab GARCH documentation (mean reversion to unconditional variance): https://vlab.stern.nyu.edu/docs/volatility/GARCH
- Portfolio Optimizer, "Volatility Forecasting: GARCH(1,1) Model": https://portfoliooptimizer.io/blog/volatility-forecasting-garch11-model/

**Regime switching**
- Hamilton, J. (1989). *Econometrica*.
- Guidolin, M. & Timmermann, A. (2007). "Asset Allocation Under Multivariate Regime Switching." *JEDC*. https://www.sciencedirect.com/science/article/abs/pii/S0165188906002272
- Guidolin, M. & Timmermann, A. (2008). "International Asset Allocation under Regime Switching, Skew, and Kurtosis Preferences." *RFS* 21(2). https://academic.oup.com/rfs/article-abstract/21/2/889/1610338
- "Improving S&P 500 Volatility Forecasting through Regime-Switching Methods" (2025). https://arxiv.org/pdf/2510.03236

**Mean reversion / variance ratios**
- Poterba, J. & Summers, L. (1988). "Mean Reversion in Stock Prices: Evidence and Implications." *JFE* 22, 27–59. https://www.nber.org/system/files/working_papers/w2343/w2343.pdf
- Fama, E. & French, K. (1988). "Permanent and Temporary Components of Stock Prices." *JPE*.
- Richardson, M. & Stock, J. (1989); Richardson, M. & Smith, T. (1991) — small-sample bias critiques. Summarized in: https://www.uu.nl/sites/default/files/rebo_use_dp_2010_10-07.pdf
- "Mean Reversion in Stock Prices? A Reappraisal" (NBER w2795). https://www.nber.org/system/files/working_papers/w2795/w2795.pdf
- Kan, R. "Exact Variance Ratio Test with Overlapping Data." https://www-2.rotman.utoronto.ca/~kan/papers/vratio3.pdf

**Machine learning / SOTA and its limits**
- Gu, S., Kelly, B. & Xiu, D. (2020). "Empirical Asset Pricing via Machine Learning." *RFS* 33(5), 2223–2273. https://academic.oup.com/rfs/article/33/5/2223/5758276 · https://dachxiu.chicagobooth.edu/download/ML.pdf
- Goyal, A., Welch, I. & Zafirov, A. (2024). "A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction." *RFS* 37(11), 3490. https://academic.oup.com/rfs/article/37/11/3490/7749383
- Xu, C. & Xie, Y. "Conformal Prediction for Time Series" (EnbPI, ICML 2021 / IEEE TPAMI). https://github.com/hamrel-cxu/EnbPI
- Gibbs, I. & Candès, E. (2021). Adaptive Conformal Inference.
- Zaffran, M. et al. (2022). "Adaptive Conformal Predictions for Time Series." *ICML*. https://proceedings.mlr.press/v162/zaffran22a/zaffran22a.pdf
- "Conformal Prediction Algorithms for Time Series Forecasting: Methods and Benchmarking" (2026). https://arxiv.org/pdf/2601.18509
- "Bias-Corrected Adaptive Conformal Inference for Multi-Horizon Time Series Forecasting" (2026). https://arxiv.org/pdf/2604.13253
- Salinas, D. et al. (2020). "DeepAR." *IJF*. GluonTS: https://www.jmlr.org/papers/volume21/19-820/19-820.pdf
- "Pretrained Time-Series Foundation Models for Financial Return Forecasting" (June 2026). https://arxiv.org/abs/2606.27100
- "Re(Visiting) Time Series Foundation Models in Finance" (2025). https://arxiv.org/html/2511.18578v1

**Practice: fan charts, Monte Carlo, communication**
- Vanguard Capital Markets Model (VCMM) methodology and 10 000-path percentile fan charts: https://corporate.vanguard.com/content/corporatesite/us/en/corp/what-we-think/investing-insights/v-family-models.html
- Pfau, W. & Young, M. "The Dangers of Monte Carlo Simulations." *Advisor Perspectives* (2023). https://www.advisorperspectives.com/articles/2023/01/10/the-dangers-of-monte-carlo-simulations
- Kitces, M. "Assessing Performance Predictiveness of Monte Carlo Models" (Brier scores; regime-based vs traditional). https://www.kitces.com/blog/monte-carlo-models-simulation-forecast-error-brier-score-retirement-planning/
- "Capital Market Expectations and Monte Carlo Simulations." *FPA Journal*. https://www.financialplanningassociation.org/article/journal/JUL16-capital-market-expectations-and-monte-carlo-simulations
- Portfolio Visualizer Monte Carlo (block bootstrap option): https://www.portfoliovisualizer.com/monte-carlo-simulation

**Packages (versions verified August 2026)**
- `arch` 8.0.0 — Python ≥3.10, pandas-3/numpy-2 ready, Meson build. https://bashtage.github.io/arch/changes.html · https://github.com/bashtage/arch
- `PyPortfolioOpt` 1.6.0 (installed) — https://github.com/PyPortfolio/PyPortfolioOpt
- `statsmodels` 0.14.6 (installed) — `tsa.regime_switching.MarkovRegression`
- `MAPIE` 1.5.0 (5 Aug 2026), Python ≥3.10 — https://github.com/scikit-learn-contrib/MAPIE · https://mapie.readthedocs.io/
- `PyMC` 6.3.1 — **Python ≥3.12 required** (Condor venv is 3.11.1) — https://pypi.org/project/pymc/
- `GluonTS` 0.17.0 — Python ≥3.10 <3.15, torch ≥2.10 — https://pypi.org/project/gluonts/
- `skfolio` 0.20.2 (13 Aug 2026) — scikit-learn-compatible portfolio optimization with uncertainty sets, stress testing, walk-forward CV; a plausible future alternative/complement to PyPortfolioOpt. https://skfolio.org/ · https://arxiv.org/abs/2507.04176
