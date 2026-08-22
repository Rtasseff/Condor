# Free & Near-Free Data Sources for the Condor Forecaster

*Research inventory — August 2026. Produced by a research agent; treat rate
limits and ToS readings as point-in-time and re-verify before depending on
them.*

## TL;DR

The single highest-leverage, lowest-risk addition is **Fama-French factor
data** (via `pandas-datareader`) — it directly unlocks factor-based μ
shrinkage and factor covariance models, which is exactly the numerics upgrade
a multi-year fan chart needs to look defensible rather than a random walk
with wide error bars. **FRED macro series** (yield-curve slope, credit
spreads, VIX) are free, well-licensed, and trivial to wire in, but the honest
reading of the predictability literature (Goyal & Welch) is that almost none
of these variables reliably beat a constant-expected-return baseline out of
sample — so they belong in the model as *regime/uncertainty-band
conditioning*, not as point-forecast drivers. **Shiller CAPE and Damodaran's
implied ERP** are the best free anchors for long-horizon expected-return
levels, which matters more for a multi-year fan chart than any short-horizon
macro signal. Everything else (single-name implied vol, most of the "new"
2026 API free tiers) is either not free enough to be useful at your scale or
not needed yet.

---

## 1. Fama-French factor returns (Ken French Data Library)

**Access method.** Two equally valid paths:
- `pandas-datareader`, which wraps the site's zipped CSVs:
  ```python
  import pandas_datareader.data as pdr
  ff5 = pdr.DataReader("F-F_Research_Data_5_Factors_2x3", "famafrench", start="1990-01-01")[0] / 100
  ```
- Direct CSV/zip download from the library index page and `pandas.read_csv`
  on the extracted file — useful to avoid the `pandas-datareader` dependency
  or for datasets it hasn't indexed (momentum, industry portfolios).

**Update cadence.** Monthly factors (3-factor, 5-factor, momentum) update
monthly with a short lag; daily factor series exist for market, size, value,
and momentum. Portfolio breakpoints and industry sorts reconstitute annually
(June) per the standard Fama-French methodology.

**Historical depth.** US factors from **July 1926**; international/regional
(developed, emerging, ex-US) from the mid-1970s–1990s depending on market.
This is far deeper history than yfinance gives for most tickers, which is
itself useful for calibrating long-horizon dispersion.

**License/ToS verdict: OK.** The data library page states only "Copyright
Eugene F. Fama and Kenneth R. French" with no explicit redistribution clause.
There's no formal open license, but the dataset is the de facto standard in
academic and industry quant research, freely mirrored by `pandas-datareader`,
WRDS, and dozens of packages with no known enforcement history against
downstream users. For Condor's use — computing factor exposures and shrinkage
targets internally, not republishing the raw factor CSVs as a product — this
is squarely fine for a 5-user hosted app. Cite Fama/French in any "data
sources" footer as good practice.

**What it unlocks.** This is the actual answer to "how do we shrink μ and
estimate covariance better for the Forecaster":
- **Factor-based μ shrinkage**: instead of shrinking each asset's historical
  mean toward a single grand mean (Jorion-style), shrink toward a factor
  model prediction (CAPM/Fama-French expected return), which is a much
  better-behaved prior for a fan chart's center line.
- **Factor covariance model**: `Σ = B Σ_f B' + D` (factor covariance plus
  idiosyncratic diagonal) is dramatically more stable than a sample
  covariance matrix once you have >20-30 assets, and is standard in
  PyPortfolioOpt's `risk_models` — directly reusable per CLAUDE.md's "prefer
  established packages" rule.
- Regressing each `AssetSet` member's returns on the 5 factors also gives
  factor *loadings*, a natural new column in `AssetSet.analysis()`.

**Integration effort.** Doesn't fit the ticker-keyed `PriceSource` protocol
(no ticker, monthly/annual cadence, multi-column factor sets, no OHLCV
shape) — cleanest as a small parallel `FactorSource` protocol (`name`,
`fetch(dataset, start) -> DataFrame`) with its own cache namespace in
`~/.condor` (weekly refresh is plenty; these datasets don't move daily). Low
effort — a few hours including the caching wrapper.

---

## 2. FRED macro series beyond the risk-free rate

**Access method.**
```python
import pandas_datareader.data as pdr
baa10y = pdr.DataReader("BAA10Y", "fred", start)   # Baa credit spread
t10y3m = pdr.DataReader("T10Y3M", "fred", start)   # yield-curve slope
cfnai  = pdr.DataReader("CFNAI",  "fred", start)   # Chicago Fed activity index
```
or the `fredapi` package (`Fred(api_key).get_series("T10Y3M")`) for more
control. Condor already has FRED wired in for Treasury yields, so this is
additive, not new plumbing.

**Update cadence.** Daily for market-derived series (T10Y3M, T10Y2Y,
BAA10Y); monthly for CFNAI, unemployment (UNRATE); revisions happen (FRED
keeps vintages via ALFRED for point-in-time backtesting discipline).

**Historical depth.** Decades — T10Y3M/BAA10Y back to the 1980s-90s, UNRATE
to 1948, CFNAI to 1967.

**License/ToS verdict: OK.** FRED's terms permit both non-commercial and
commercial use of API data with attribution, subject to a published fair-use
rate limit (120 requests/minute/key) and a prohibition on implying Fed
endorsement. A handful of third-party series (e.g., S&P/Case-Shiller) carry
extra restrictions on *bulk redistribution*, but none of the series above
fall into that bucket. Fine for a 5-user hosted app.

**Evidence they predict returns — the honest version.**
- **In-sample, several of these do "work"**: term spread and credit spreads
  correlate with business-cycle stage, and the near-term forward spread
  (Engstrom-Sharpe) has documented predictive power for recession
  probability and subsequent 4-quarter equity returns.
- **Out-of-sample, the record is much weaker.** Goyal & Welch (2008) showed
  essentially none of the standard predictors (dividend yield, term spread,
  default spread, …) beat a simple historical-mean forecast out-of-sample
  over the full post-war period. The 2024 follow-up with Zafirov
  (*Review of Financial Studies* 37(11)) re-ran this against 29 newer
  variables: **more than a third lose in-sample significance entirely, and
  of those that remain significant in-sample, about half still fail
  out-of-sample.** A small number of variables (short-rate-related, some
  valuation ratios) survive both tests, but the honest consensus — reaffirmed
  in the 2025 data update — is that return predictability from macro
  variables is weak, unstable across sub-periods, and easy to overfit.
- **Practical implication for Condor**: don't build a model that says
  "credit spreads are wide, therefore expected return is X.YY% higher." Use
  these series as **regime/uncertainty conditioning** for the fan chart's
  *width* (widen bands when the curve is inverted or spreads are elevated —
  realized volatility and drawdown risk empirically do cluster with these
  signals even where the *mean* signal is unreliable), not as a
  point-forecast input.

**Integration effort.** Same `FactorSource`/macro protocol as Fama-French,
keyed by FRED series ID. Trivial — more series IDs through the same door.

---

## 3. Valuation anchors: Shiller CAPE and Damodaran implied ERP

### Shiller CAPE / cyclically-adjusted P/E

**Access.** Direct spreadsheet download from Robert Shiller's Yale page
(`ie_data.xls`, mirrored at `shillerdata.com`); `pandas.read_excel` with a
header-row skip. No package, no API key.

**Cadence / depth.** Monthly; monthly US data back to **1871** — by far the
longest series in this inventory, valuable for long-horizon dispersion
calibration even if only recent decades feed the mean.

**License/ToS verdict: OK (attribute).** No explicit license; openly reused
for decades (multpl.com, quant blogs, Quandl mirrors) without known
restriction on non-commercial or internal analytical use. Attribute Shiller;
treat as low-risk rather than formally cleared.

**What it unlocks.** CAPE is the standard free anchor for **long-horizon
(10-year) expected equity return** — high CAPE historically associates with
lower subsequent 10-year real returns. Exactly the shape of prior a
multi-year fan chart needs: a valuation-conditioned center path rather than
flat historical-mean extrapolation, with the caveat (worth stating in-app)
that CAPE's *timing* power over any single year is weak — it's a
long-horizon anchor, not a trading signal.

### Damodaran implied equity risk premium

**Access.** Direct `.xls`/`.xlsx` from NYU Stern (`histimpl.xls` for the
historical implied-ERP time series; current-year ERP by country/sector on
the same site). `pandas.read_excel`, no key.

**Cadence / depth.** Monthly-ish updates to current implied ERP; the annual
"Equity Risk Premiums" paper (2026 edition on SSRN) republished yearly.
Annual implied ERP series back to the **1960s**.

**License/ToS verdict: OK.** Published explicitly for practitioner/academic
reuse (no paywall, no registration), universally cited without licensing
friction. Attribute.

**What it unlocks.** A market-implied (rather than historical-average)
equity risk premium — a second, methodologically independent long-horizon
anchor to cross-check CAPE-implied expected returns, useful for
sanity-bounding the Forecaster's terminal-year fan spread.

**Integration effort (both).** Neither fits `PriceSource`. Same
`FactorSource`-style protocol as §1/§2 with a long cache TTL (updates at
most monthly). An afternoon for both combined.

---

## 4. Volatility: VIX, term structure, single-name IV, realized-vol fallback

**VIX and VIX3M via FRED.**
```python
vix   = pdr.DataReader("VIXCLS", "fred", start)   # spot VIX, 1990–present
vix3m = pdr.DataReader("VXVCLS", "fred", start)   # 3-month VIX (term structure point)
```
Daily, close-only. License: **OK** — FRED's redistribution of the
CBOE-sourced series is already cleared at the FRED layer, a cleaner path
than scraping CBOE's own CSVs (whose site ToS is stricter). The VIX/VIX3M
ratio (contango vs. backwardation) is a standard, cheap **market-implied
uncertainty signal** — directly useful for scaling the Forecaster's
near-term fan width, and a genuinely well-supported use (unlike the §2 macro
predictability question, term-structure level and slope are well-documented
forward-looking risk proxies).

**Single-name implied volatility, free: no reliable source exists (2026).**
IEX Cloud (a past free option) shut down; free/demo tiers of EODHD,
Intrinio, and similar offer at most a single hard-coded demo ticker. Genuine
single-name IV/options-surface data (ORATS, IVolatility, Intrinio, Unusual
Whales, EODHD's real options API) is paid. Don't build anything in the
Forecaster that assumes free single-name IV.

**Fallback: realized volatility from our own daily closes.** The right
answer for per-asset near-term vol: EWMA or GARCH(1,1) (via `arch` or
`statsmodels`) on the return series already in the store. Zero licensing
question, zero new integration — new numerics in an engine module only.
This should be the default per-asset vol input; VIX/VIX3M is the
market-wide overlay/regime signal on top.

---

## 5. Fundamentals via yfinance / Tiingo free tiers

**yfinance** (`Ticker.financials`, `.balance_sheet`, `.earnings`). Free, no
key, works today, but it's an unofficial wrapper around undocumented Yahoo
endpoints. Yahoo's ToS restricts automated access and redistribution;
enforcement against small non-commercial tools has been essentially
nonexistent, but there is no license grant to point to. **Verdict: gray.**
For a 5-user, non-resold hosted tool this is a reasonable risk (already
taken for prices) — don't expand it into a customer-facing "download our
fundamentals" feature, and keep the Tiingo-failover pattern.

**Tiingo fundamentals.** Free tier has been squeezed (sources in 2026
variously say 25–1,000 requests/day — the discrepancy itself signals the
terms are shifting; check the live dashboard), and free-tier fundamentals
depth is capped at ~5 years vs 15+ paid. Tiingo's ToS gates "commercial use"
behind paid plans. **Verdict: gray-to-OK** for Condor specifically (not
resold), but read their definition of "commercial" before leaning on it;
the Power tier is cheap enough to just buy if fundamentals become
load-bearing.

**Integration effort.** Both map cleanly onto a `FundamentalsSource`
protocol shaped like `PriceSource` (`name`, `fetch(ticker, start) ->
DataFrame` of quarterly/annual line items). Low effort given the existing
failover plumbing.

---

## 6. What's genuinely new/worth knowing in 2026

**SEC EDGAR XBRL company-facts API — the standout.**
```python
import requests
r = requests.get(
    "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
    headers={"User-Agent": "Condor Funds research@yourdomain.com"},
)
```
- **Cadence**: per filing (10-Q/10-K, so quarterly/annual per company).
- **Depth**: back to roughly 2009 for most large-caps (XBRL mandate),
  sparser before.
- **License/ToS: OK — the best story in this report.** SEC filings are
  public-disclosure data with no copyright restriction; no key, no signup,
  no billing — only a descriptive `User-Agent` header and a generous
  published rate limit (10 req/s per IP, no daily cap).
- **Unlocks**: raw, audited fundamentals (revenue, book value, shares
  outstanding, EPS) as ground truth against yfinance/Tiingo, or as primary
  source given CIK↔ticker mapping and XBRL-tag normalization work.
- **Effort: moderate.** Fits `FundamentalsSource`, but XBRL tags vary across
  filers/GAAP vintages (`Revenues` vs
  `RevenueFromContractWithCustomerExcludingAssessedTax`), so the fetch needs
  a small tag-reconciliation layer.

**Alpha Vantage.** Free tier throttled to ~25 requests/day, 5/min. Not
usable for a multi-asset app. **Skip.**

**EODHD.** Free tier ~20 requests/day; paid entry tier is inexpensive with
good fundamentals/options breadth — a "consider later if paying," not a free
source. **Skip for now**; revisit if single-name options/IV is ever needed.

**Polygon.io.** Free tier: 5 req/min, end-of-day delayed aggregates. Not a
meaningful upgrade over yfinance here. **Skip.**

**Nasdaq Data Link (ex-Quandl).** Anonymous ~50 calls/day; the useful free
datasets (old WIKI equities) were deprecated years ago and what remains
largely duplicates FRED. **Skip — mostly redundant now.**

---

## Summary table

| Source | Access | Cadence | History | ToS verdict (5-user hosted) | Unlocks | Effort |
|---|---|---|---|---|---|---|
| Fama-French factors | `pandas-datareader` / CSV | Monthly (daily variants) | 1926– | OK | Factor μ-shrinkage, factor covariance | Low — new `FactorSource` protocol |
| FRED T10Y3M, BAA10Y, UNRATE, CFNAI | `pandas-datareader`/`fredapi` | Daily/monthly | 1948–1990s– | OK | Regime/uncertainty-band conditioning (not point forecasts) | Trivial — extend existing FRED client |
| Shiller CAPE | Direct `.xls` | Monthly | 1871– | OK (attribute) | Long-horizon expected-return anchor | Low |
| Damodaran implied ERP | Direct `.xls` | ~Monthly | 1960s– | OK (attribute) | Independent long-horizon ERP anchor | Low |
| VIX / VIX3M | FRED (`VIXCLS`/`VXVCLS`) | Daily | 1990– | OK | Implied-vol overlay, term-structure signal | Trivial |
| Single-name implied vol (free) | — | — | — | N/A | **No reliable free source in 2026** | — |
| Realized vol (own closes) | Internal | Daily | Store depth | OK (own data) | Per-asset vol via EWMA/GARCH | Engine-only |
| yfinance fundamentals | `yfinance` | Quarterly/annual | Varies | Gray (unofficial, low risk) | Earnings, book value | Low |
| Tiingo fundamentals | Tiingo API | Quarterly/annual | 5yr free | Gray (check "commercial" clause) | Failover fundamentals | Low |
| SEC EDGAR XBRL | `data.sec.gov` REST | Per filing | ~2009– | **OK — best ToS here** | Ground-truth fundamentals | Moderate (tag normalization) |
| Alpha Vantage / EODHD / Polygon free / Nasdaq DL | REST | — | — | OK but too rate-limited | — | Skip |

---

## Ranked shortlist for the Forecaster

1. **Fama-French factors.** Highest modeling payoff for the lowest cost —
   factor-shrunk μ and a factor covariance model are the biggest quality
   upgrade available to the fan chart's center path and asset-level
   dispersion; deep, free, low-risk data.
2. **FRED yield-curve slope + BAA10Y + VIX/VIX3M.** Nearly zero integration
   cost; weak *point-forecast* predictors (Goyal & Welch) but well-supported
   *uncertainty-regime* signals — widen/narrow the fan bands, don't move the
   center line.
3. **Shiller CAPE + Damodaran implied ERP** (one shortlist item —
   complementary anchors, both cheap). The right lever for long-horizon
   expected-return *levels*, which is what a multi-year fan chart needs and
   short-horizon macro can't give.
4. **SEC EDGAR XBRL company facts** — the fundamentals path with actually
   clean licensing; cross-check now or primary source once the moderate
   tag-normalization effort is worth it.

**Skip for now**: Alpha Vantage, EODHD free tier, Polygon.io free tier,
Nasdaq Data Link. Revisit EODHD or a paid options vendor (Intrinio/ORATS)
only *if* the Forecaster later needs real single-name implied vol.

---

## A note on the `PriceSource` protocol

Fundamentals (yfinance, Tiingo, SEC EDGAR) are ticker-keyed and fit a
sibling `FundamentalsSource` protocol with the same signature as
`PriceSource`. Factor, macro, and valuation series (§1-3, plus VIX) are
*not* ticker-keyed, have different cadences, and return named series rather
than OHLCV frames — forcing them through `PriceSource` would be awkward.
Cleanest is a small parallel `FactorSource` protocol (`name`,
`fetch(series_id, start) -> Series | DataFrame`) with its own cache
namespace and a longer default TTL.

---

## References

- Kenneth R. French Data Library — https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- pandas-datareader: Fama-French — https://pandas-datareader.readthedocs.io/en/latest/readers/famafrench.html
- FRED API Terms of Use — https://fred.stlouisfed.org/docs/api/terms_of_use.html
- Goyal, Welch, Zafirov (2024), RFS 37(11) — https://academic.oup.com/rfs/article/37/11/3490/7749383
- Goyal, Welch, Zafirov — SSRN — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3929119
- Amit Goyal's predictor data page — https://sites.google.com/view/agoyal145
- FRED: BAA10Y — https://fred.stlouisfed.org/series/BAA10Y
- NY Fed: yield curve as leading indicator — https://www.newyorkfed.org/research/capital_markets/ycfaq
- Fed note: "(Don't Fear) The Yield Curve, Reprise" — https://www.federalreserve.gov/econres/notes/feds-notes/dont-fear-the-yield-curve-reprise-20220325.html
- Chicago Fed: CFNAI — https://www.chicagofed.org/research/data/cfnai/about
- Shiller data — http://www.econ.yale.edu/~shiller/data.htm / https://shillerdata.com/
- Damodaran implied ERP — https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histimpl.html
- Damodaran ERP 2026 edition (SSRN) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6361419
- FRED: VIXCLS — https://fred.stlouisfed.org/series/VIXCLS
- SEC EDGAR APIs — https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- Tiingo docs — https://www.tiingo.com/documentation/
- yfinance — https://pypi.org/project/yfinance/
- Polygon.io rate limits — https://polygon.io/knowledge-base/article/what-is-the-request-limit-for-polygons-restful-apis
- Nasdaq Data Link rate limits — https://docs.data.nasdaq.com/docs/rate-limits-1
