# Condor CLI — from zero to a frontier

For one-off questions from a terminal, without starting the web app.
Everything here assumes nothing but a Mac/Linux shell, Python 3.11+, and
an internet connection.

## 1. One-time setup

```bash
git clone git@github.com:Rtasseff/Condor.git
cd Condor
python3 -m venv .venv
source .venv/bin/activate        # do this in every new terminal session
pip install -r requirements.txt
```

That's it — no database, no accounts, no API keys. (Optional: a free
[tiingo.com](https://www.tiingo.com) API key in the `TIINGO_API_KEY`
environment variable adds an official backup data source for when Yahoo
misbehaves.)

## 2. First command

```bash
python -m condor analyze MSFT NEE CVX
```

The first run downloads ~10 years of daily prices per ticker (a few
seconds each) into a local store at `~/.condor/prices/`; every later run
reads from there instantly. You'll see something like:

```
MSFT, NEE, CVX — robust statistics, 2016-08-22 to 2026-08-21 (2,514 trading days)
risk-free 3.87% (3-mo T-bill, FRED, as of 2026-08-20)

Asset    Exp. return  Dispersion
MSFT          25.82%      19.62%
NEE           27.96%      17.82%
CVX           23.64%      19.35%

Portfolio              Ret        Disp  Sharpe   Weights
Equal weights       25.81%      11.68%    1.88   MSFT 33.3% · NEE 33.3% · CVX 33.3%
Min dispersion      25.93%      11.63%    1.90   MSFT 30.3% · NEE 37.8% · CVX 31.9%
Tangency            26.11%      11.68%    1.90   MSFT 30.1% · NEE 42.0% · CVX 27.9%
```

How to read it:

- **Exp. return / Dispersion** — annualized expected return and spread
  (risk) estimated from the last 10 years of daily data. "Robust" means
  median-based statistics that shrug off crash-day outliers; add
  `--method normal` for the classical mean/covariance versions.
- **Equal weights** — the naive 1/N split, as a baseline.
- **Min dispersion** — the least-risky mix of these assets.
- **Tangency** — the mix with the best return *per unit of risk*
  (highest Sharpe ratio); the textbook "reasonable choice".
- The **risk-free rate** is fetched live (3-month US T-bill from FRED)
  and is what the Sharpe ratio compares against.

Note how the portfolios' dispersion (~11.7%) is far below every single
asset's (~18–20%) — that's diversification doing its job, and it's the
whole point of the tool.

## 3. The other commands

```bash
# Score a mix you already have (weights in any scale — they're normalized):
python -m condor portfolio MSFT=30 NEE=40 CVX=30

# The whole efficient frontier, point by point:
python -m condor frontier MSFT NEE CVX

# ...as a CSV for a spreadsheet, or an interactive chart:
python -m condor frontier MSFT NEE CVX --csv > frontier.csv
python -m condor frontier MSFT NEE CVX --html chart.html   # open in a browser

# What's in the local price store, refresh it, clean it out:
python -m condor data ls
python -m condor data update
python -m condor data purge AAPL
```

## 4. Options that work everywhere

| Option | Meaning | Default |
|---|---|---|
| `--method robust\|normal` | median/CoMAD vs mean/Ledoit-Wolf statistics | `robust` |
| `--years N` | lookback window | `10` |
| `--rf X` | risk-free rate: `4` = 4%, `0.04` works too | live FRED 3-mo T-bill |
| `--source yfinance\|tiingo` | pin the data provider | yfinance, tiingo fallback |
| `--json` | raw payload instead of a table (for scripts) | off |

`python -m condor <command> --help` shows the full list per command.

## 5. When something goes wrong

- **`error: No price data returned for 'XYZ'`** — the ticker doesn't
  exist (or Yahoo doesn't carry it). Tickers are the exchange symbols:
  `BRK-B`, not `BRK.B`.
- **Only N daily observations** — the asset is too young (needs ≥60
  shared trading days with the others). Shorten `--years` or drop it.
- **Yahoo rate-limits / flakes** — wait a minute and retry, or set
  `TIINGO_API_KEY` so the fallback kicks in.
- **Stale numbers?** — data refreshes automatically once a day;
  `python -m condor data update` forces it.
