"""Condor Funds v2 analytics core.

Portfolio construction and optimization on top of established tools
(PyPortfolioOpt / cvxpy), with the legacy Condor "Robust" statistics
(median / MAD / CoMAD) preserved as a first-class estimation method.
"""

from .data import fetch_prices, DataFetchError
from .stats import asset_returns, expected_annual, risk_matrix_annual
from .frontier import compute_analysis

__all__ = [
    "fetch_prices",
    "DataFetchError",
    "asset_returns",
    "expected_annual",
    "risk_matrix_annual",
    "compute_analysis",
]
