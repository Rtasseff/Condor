"""Condor Funds v2 analytics core.

Portfolio construction and optimization on top of established tools
(PyPortfolioOpt / cvxpy), with the legacy Condor "Robust" statistics
(median / MAD / CoMAD) preserved as a first-class estimation method.

Object API (preferred):   AssetSet -> Portfolio / Frontier   (model.py)
Procedural facade:        compute_analysis(prices, ...)     (frontier.py)
Engine:                   stats.py (μ, Σ), frontier.py (_perf, _solve)
"""

from .data import fetch_prices, DataFetchError, PriceStore, risk_free_rate
from .stats import asset_returns, expected_annual, risk_matrix_annual
from .frontier import compute_analysis
from .model import Asset, AssetSet, Forecast, Frontier, Portfolio

__all__ = [
    "fetch_prices",
    "DataFetchError",
    "PriceStore",
    "risk_free_rate",
    "asset_returns",
    "expected_annual",
    "risk_matrix_annual",
    "compute_analysis",
    "Asset",
    "AssetSet",
    "Portfolio",
    "Frontier",
    "Forecast",
]
