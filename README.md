# Condor Funds v2

Relaunch of the Condor Funds project (2023–2024): tools that make rigorous,
diversified portfolio building accessible to people who've never invested.

## Layout

| Path | What it is |
|---|---|
| `ARCHITECTURE.md` | Layering rules and where new features go — read before changing `condor/` or `web/` |
| `BACKLOG.md` | Prioritized backlog (Now / Next / Later / Done) |
| `context/` | Everything from round one — start with [`context/CONTEXT.md`](context/CONTEXT.md) |
| `context/pitch/` | Investor pitch deck; `concept_slides/` are the UI-vision mockups |
| `context/legacy/` | Snapshot of the real code from `condor_test` (reference only) |
| `drive_export/` | Text dump of the condorfunds@gmail.com work drive (`INDEX.md` lists all 43 docs). `files/` holds originals + bulk market data and stays out of git. |
| `condor/` | v2 analytics core: assets, portfolios, frontier optimization |
| `notebooks/` | `01_verify_core.ipynb` — the verification story, readable and re-runnable |
| `web/` | v2 Django app: the portfolio Explorer UI |

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python web/manage.py migrate           # tables: saved portfolios, accounts
python web/manage.py createsuperuser   # your login (first run only)
python web/manage.py runserver
```

Then open http://127.0.0.1:8000/ and sign in. Every page requires a
login; add teammates at http://127.0.0.1:8000/admin (Users → Add).
Portfolios can be saved and shared by URL (`/p/<id>` — readable by any
logged-in user, editable only by the owner). "My account" (`/account`)
tracks a pretend-or-mirrored real account as a ledger: deposits and
trades in, value at last close out, drift vs your setpoint,
whole-share rebalancing plans, scheduled contributions with a
where-should-it-go DCA plan and login reminder, and a whole-account
forecast (holdings + cash at the T-bill rate) (ADR 0004). A CSV ledger kept
elsewhere can be mirrored read-only with
`python web/manage.py import_ledger LEDGER.csv [--targets T.csv] [--payin P.csv] [--rules R.csv] --user NAME --replace`
(format: `docs/LEDGER-FORMAT.md`, ADR 0005): average cost, realized and
unrealized gain, dividends/interest/fees as return, one currency per
account, and bills that accrete to nominal; `export_ledger` writes the
same format back out. `/account?account=<id>` switches between accounts.
With the format's v1.1 files (`--targets` with `timing`/`line`, `--payin`,
`--rules`; ADR 0007) a mirror also shows the pay-in tracker (progress per
line, the whole-share buy list for tranche k with catch-up sizing, budget
trim and the reservoir sale or purchase, completion), rule alerts (index
below its 52-week high, position below average cost, drift, muted during
the pay-in), a money-weighted return (XIRR) beside the time-weighted one,
and a combined USD + EUR total across your accounts. All of it is advice:
nothing is bought for you.
A mirror also has a **Check against your broker** card: what your broker should
show if the ledger is complete (cash booked to the cent per event, securities
value and account value at the last close), with boxes to type what it does
show and a match / mismatch in words. Cash is the authoritative check. Read-only
(`POST /api/account/reconcile`); nothing typed is stored.
Everything else recomputes live from market data.

Core analytics can also be used directly:

```python
from condor import fetch_prices, AssetSet

prices = fetch_prices(["MSFT", "NEE", "CVX"], years=10)
aset = AssetSet(prices, method="robust")      # owns μ and Σ for this set
aset.summary()                                # expected return & dispersion per asset

# premium mode: expected return = today's T-bill + premium measured on
# excess returns over the daily T-bill history (docs/decisions/0006)
from condor import risk_free_history, risk_free_rate
rf = risk_free_rate()["rate"]
aset = AssetSet(prices, method="robust", rf_history=risk_free_history(), rf_level=rf)
aset.premiums                                 # per-asset premium over T-bills

# assumptions mode: limits + a long-run view (docs/decisions/0008)
from condor.assumptions import Assumptions
a = Assumptions.from_dict({"name": "Mine",
    "constraints": {"bounds": {"MSFT": {"max": 0.4}}}})
under = aset.with_options(prior=a.prior, reference_prices=fetch_prices(["VT"])["VT"])
under.frontier(0.04, constraints=a.constraints).gaps(under.portfolio({"MSFT": 1}))

mine = aset.portfolio({"MSFT": 0.5, "NEE": 0.3, "CVX": 0.2})
mine.expected_return, mine.dispersion, mine.sharpe(risk_free_rate=0.04)
mine.history().to_dict()                      # worst fall, worst year, growth/yr
                                              # (fixed weights, rebalanced)
mine.scenarios()                              # return / worst fall in named stress periods
aset.stability(0.04, n=100)                   # how far the best mix moves on reshuffled history

fr = aset.frontier(risk_free_rate=0.04)       # every point is a Portfolio
fr.tangency.weights                           # the 'reasonable guess'
fr.at_return(0.20).weights                    # pick any point on the curve
fr.min_vol, fr.cal, fr.curve                  # anchors and plotting helpers

# a portfolio is an asset of assets: nest it alongside a benchmark
AssetSet.from_members([mine, fetch_prices(["SPY"])["SPY"]]).summary()
```

`compute_analysis(prices, ...)` is the one-call procedural facade the web view
uses; it returns the same numbers as a plain dict.

### CLI

One-off questions without starting Django (uses the same store and engine).
Cold start to first frontier: [`docs/CLI.md`](docs/CLI.md).

```bash
python -m condor analyze MSFT NEE CVX            # stats + min-vol + tangency
python -m condor portfolio MSFT=30 NEE=40 CVX=30 # a given mix (any scale)
python -m condor frontier MSFT NEE CVX --csv     # the curve, point by point
python -m condor frontier MSFT NEE CVX --html chart.html
python -m condor data ls                         # what the price store holds
python -m condor portfolio MSFT=30 NEE=40 CVX=30 --assumptions mine.json
                                                 # ...and under your limits + long-run view
```

`--rf` defaults to the live FRED 3-month T-bill; pass `--rf 4` (percent)
or `--rf 0.04` to override. `--method robust|normal`, `--json` everywhere.
Expected returns are the T-bill rate plus each asset's premium over T-bills;
`--no-premium` gives the raw historical averages instead (see
[`docs/CLI.md`](docs/CLI.md)).

## Layers

| Module | Role |
|---|---|
| `condor/model.py` | Domain objects: `Asset`, `AssetSet`, `Portfolio`, `Frontier` |
| `condor/stats.py` | Estimation engine: expected returns, risk matrix (normal / robust), equilibrium prior / blend / views |
| `condor/assumptions.py` | `Assumptions`: weight limits + a long-run view, validated (pure; ADR 0008) |
| `condor/frontier.py` | Optimization engine (`_perf`, `_solve`) + `compute_analysis` facade |
| `condor/history.py` | History engine: max drawdown, calendar-year returns, CAGR, named stress windows (pure) |
| `condor/stability.py` | Stability engine: block-bootstrap indices and percentile summary for the tangency-weight bands (pure) |
| `condor/forecast.py` | Forecast engine: closed-form fan-chart bands with estimation-error overlay |
| `condor/accounting.py` | Account engine: ledger replay (cost basis, income, bills), valuation/TWR, whole-share rebalance plans |
| `condor/ledger_io.py` | Ledger exchange format v1.1: validating CSV readers (ledger, targets, pay-in, rules) / writer (pure; no Django) |
| `condor/payin.py` | Pay-in engine: whole-share catch-up buy lists, budget trim, reservoir trade, completion |
| `condor/alerts.py` | Rule alerts: below-high / below-cost / drift, and how fired rules extend the buy list |
| `condor/cli.py` | CLI: `python -m condor analyze/portfolio/frontier/data` |
| `condor/data/` | Price store (`~/.condor/prices`, Parquet) + sources (yfinance, Tiingo) + FRED risk-free rate |

Run tests with `python -m pytest tests/` — `test_verification.py` pins the
engine to the legacy code, closed-form Markowitz, and the 2024 notebook's
numbers; `test_model.py` pins the object API to the engine.
