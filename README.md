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
logged-in user, editable only by the owner); everything else recomputes
live from market data.

Core analytics can also be used directly:

```python
from condor import fetch_prices, AssetSet

prices = fetch_prices(["MSFT", "NEE", "CVX"], years=10)
aset = AssetSet(prices, method="robust")      # owns μ and Σ for this set
aset.summary()                                # expected return & dispersion per asset

mine = aset.portfolio({"MSFT": 0.5, "NEE": 0.3, "CVX": 0.2})
mine.expected_return, mine.dispersion, mine.sharpe(risk_free_rate=0.04)

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
```

`--rf` defaults to the live FRED 3-month T-bill; pass `--rf 4` (percent)
or `--rf 0.04` to override. `--method robust|normal`, `--json` everywhere.

## Layers

| Module | Role |
|---|---|
| `condor/model.py` | Domain objects: `Asset`, `AssetSet`, `Portfolio`, `Frontier` |
| `condor/stats.py` | Estimation engine: expected returns, risk matrix (normal / robust) |
| `condor/frontier.py` | Optimization engine (`_perf`, `_solve`) + `compute_analysis` facade |
| `condor/cli.py` | CLI: `python -m condor analyze/portfolio/frontier/data` |
| `condor/data/` | Price store (`~/.condor/prices`, Parquet) + sources (yfinance, Tiingo) + FRED risk-free rate |

Run tests with `python -m pytest tests/` — `test_verification.py` pins the
engine to the legacy code, closed-form Markowitz, and the 2024 notebook's
numbers; `test_model.py` pins the object API to the engine.
