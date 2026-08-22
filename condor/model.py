"""Domain model: Asset -> AssetSet -> Portfolio, plus Frontier.

A thin object layer over the numeric engine (`stats.py`, `frontier.py`).
The objects own *state that travels together* — a set of assets and the
μ / Σ estimated for it under one method — and hand every number to the
engine functions, so the verification suite pins both APIs at once.

    aset = AssetSet(prices, method="robust")
    mine = aset.portfolio({"MSFT": 0.5, "NEE": 0.3, "CVX": 0.2})
    mine.expected_return, mine.dispersion, mine.sharpe(rf=0.04)

    fr = aset.frontier(risk_free_rate=0.04)
    fr.tangency.weights            # the 'reasonable guess'
    fr.at_return(0.12).weights     # any point on the curve
    fr.min_vol.to_dict(rf=0.04)    # UI payload shape

Design notes (the full rules live in ARCHITECTURE.md — read it before
adding features; new capabilities become methods here, numerics go in an
engine module as pure functions):

- An `AssetSet` also owns the *return-calculation options* (metric,
  timeframe, samp_int, basis) that decide what series μ / Σ are estimated
  from; `with_options()` is the immutable sibling of `with_method()`.
- `Asset` is identity only (ticker, name).  Statistics are estimated for
  the *set*, vectorized — never asset-by-asset — so μ and Σ stay
  consistent and the per-pair CoMAD semantics live in one place.
- `Portfolio` *has* an `AssetSet` (composition, not inheritance).
- "A portfolio is an asset of assets": a `Portfolio` exposes a daily
  `returns` series and a prices-like `value_index`, so it can be a member
  of another `AssetSet` (`AssetSet.from_members`).  Its stats are then
  re-estimated from its own return series like any other asset.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Iterable, Iterator, Mapping

import numpy as np
import pandas as pd

from . import stats
from .frontier import N_FRONTIER_POINTS, _perf, _solve, _weights_dict

__all__ = ["Asset", "AssetSet", "Portfolio", "Frontier"]

_UNSET = object()  # "argument not given", where None is a meaningful value


# ----------------------------------------------------------------------
# Asset
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Asset:
    """An investable thing, by identity.  Numbers live on the AssetSet."""

    ticker: str
    name: str | None = None

    def __str__(self) -> str:
        return self.ticker


# ----------------------------------------------------------------------
# AssetSet
# ----------------------------------------------------------------------
class AssetSet:
    """A set of assets with μ and Σ estimated under one method.

    prices: DataFrame of aligned prices, one column per asset (tickers as
            column names), DatetimeIndex ascending.
    method: "normal" (mean / Ledoit-Wolf) or "robust" (median / CoMAD).

    How the return series behind μ and Σ is built is owned here too, as
    read-only options passed straight to the engine (see `stats.py`; all
    default to the daily/relative/arithmetic behaviour):

    metric:     "relative" or "log"
    timeframe:  "D" (1-day returns, x252) or "M" (21-day returns, x12)
    samp_int:   keep every n-th return row; None = the timeframe default
                (1 for "D", 20 for "M", which de-overlaps 21-day windows)
    basis:      "arithmetic" or "geometric" expected return ("normal" only)

    Estimates are computed lazily once and cached; an AssetSet is treated
    as immutable — use `with_method()` / `with_options()` to re-estimate.
    """

    def __init__(self, prices: pd.DataFrame, method: str = "normal",
                 names: Mapping[str, str] | None = None, *,
                 metric: str = "relative", timeframe: str = "D",
                 samp_int: int | None = None, basis: str = "arithmetic"):
        if not isinstance(prices, pd.DataFrame) or prices.shape[1] == 0:
            raise ValueError("prices must be a non-empty DataFrame (one column per asset)")
        if prices.columns.has_duplicates:
            raise ValueError("prices has duplicate tickers")
        stats._check_method(method)
        stats._check_metric(metric)
        stats._check_basis(basis)
        self.prices = prices
        self.method = method
        self._metric = metric
        self._timeframe = timeframe
        self._samp_int = stats.resolve_samp_int(timeframe, samp_int)
        self._basis = basis
        names = names or {}
        self.assets: tuple[Asset, ...] = tuple(
            Asset(str(t), names.get(str(t))) for t in prices.columns
        )

    # -- return-calculation options (read-only) --------------------------
    @property
    def metric(self) -> str:
        return self._metric

    @property
    def timeframe(self) -> str:
        return self._timeframe

    @property
    def samp_int(self) -> int:
        return self._samp_int

    @property
    def basis(self) -> str:
        return self._basis

    @property
    def _options(self) -> dict:
        """The return-calculation options, as engine keyword arguments."""
        return {"metric": self._metric, "timeframe": self._timeframe,
                "samp_int": self._samp_int, "basis": self._basis}

    # -- identity -------------------------------------------------------
    @property
    def tickers(self) -> list[str]:
        return [a.ticker for a in self.assets]

    def __len__(self) -> int:
        return len(self.assets)

    def __iter__(self) -> Iterator[Asset]:
        return iter(self.assets)

    def __contains__(self, ticker: object) -> bool:
        return ticker in self.tickers

    def __getitem__(self, ticker: str) -> Asset:
        for a in self.assets:
            if a.ticker == ticker:
                return a
        raise KeyError(ticker)

    def __repr__(self) -> str:
        # only non-default options are shown, so the common case stays short
        plain = {"metric": "relative", "timeframe": "D", "basis": "arithmetic",
                 "samp_int": stats.default_samp_int(self._timeframe)}
        extra = "".join(f", {k}={v!r}" for k, v in self._options.items()
                        if v != plain[k])
        return (f"AssetSet({self.tickers}, method={self.method!r}{extra}, "
                f"{self.start}..{self.end}, n_days={self.n_days})")

    # -- data window ----------------------------------------------------
    @property
    def start(self) -> str:
        return str(self.prices.index[0].date())

    @property
    def end(self) -> str:
        return str(self.prices.index[-1].date())

    @property
    def n_days(self) -> int:
        return int(len(self.prices))

    # -- estimates (engine calls, cached) --------------------------------
    @cached_property
    def returns(self) -> pd.DataFrame:
        """The return series the estimates are built on, one column per asset.

        Daily relative returns by default; `metric` / `timeframe` /
        `samp_int` change what one row means.
        """
        return stats.asset_returns(self.prices, metric=self._metric,
                                   timeframe=self._timeframe,
                                   samp_int=self._samp_int)

    @cached_property
    def expected_returns(self) -> pd.Series:
        """Annualized expected return per asset (μ)."""
        return stats.expected_annual(self.prices, method=self.method,
                                     **self._options)

    @cached_property
    def risk_matrix(self) -> pd.DataFrame:
        """Annualized co-dispersion matrix (Σ), PSD."""
        return stats.risk_matrix_annual(self.prices, method=self.method,
                                        metric=self._metric,
                                        timeframe=self._timeframe,
                                        samp_int=self._samp_int)

    # short math aliases, handy in notebooks
    @property
    def mu(self) -> pd.Series:
        return self.expected_returns

    @property
    def sigma(self) -> pd.DataFrame:
        return self.risk_matrix

    @property
    def dispersions(self) -> pd.Series:
        """Annualized dispersion (σ) per asset — sqrt of Σ's diagonal."""
        return pd.Series(np.sqrt(np.diag(self.risk_matrix.to_numpy())),
                         index=self.risk_matrix.index, name="dispersion")

    def asset_points(self) -> list[dict]:
        """Per-asset (ret, vol) points, UI payload shape."""
        return stats.asset_points(self.expected_returns, self.risk_matrix)

    def summary(self) -> pd.DataFrame:
        """One row per asset: expected_return, dispersion."""
        return pd.DataFrame({"expected_return": self.expected_returns,
                             "dispersion": self.dispersions})

    def with_method(self, method: str) -> "AssetSet":
        """Same assets and prices, different estimation method."""
        return self.with_options(method=method)

    def with_options(self, *, method: str | None = None,
                     metric: str | None = None, timeframe: str | None = None,
                     samp_int=_UNSET, basis: str | None = None) -> "AssetSet":
        """Same assets and prices, re-estimated under different options.

        Anything left out is carried over, and an all-unchanged call
        returns `self`.  One exception, so the legacy defaults stay
        reachable: changing the timeframe without naming a `samp_int`
        re-derives it from the new timeframe (1 for "D", 20 for "M").
        """
        current = self._options | {"method": self.method}
        opts = dict(current)
        for key, value in (("method", method), ("metric", metric),
                           ("timeframe", timeframe), ("basis", basis)):
            if value is not None:
                opts[key] = value
        if samp_int is not _UNSET:
            opts["samp_int"] = samp_int
        elif opts["timeframe"] != self._timeframe:
            opts["samp_int"] = None  # the new timeframe's default
        opts["samp_int"] = stats.resolve_samp_int(opts["timeframe"],
                                                  opts["samp_int"])
        if opts == current:
            return self
        return AssetSet(self.prices,
                        names={a.ticker: a.name for a in self.assets if a.name},
                        **opts)

    # -- portfolios over this set ---------------------------------------
    def _as_weight_array(self, weights) -> np.ndarray:
        tickers = self.tickers
        if weights is None:
            return np.ones(len(tickers)) / len(tickers)
        if isinstance(weights, Portfolio):
            weights = weights.weights
        if isinstance(weights, pd.Series):
            weights = weights.to_dict()  # by ticker, not position
        if isinstance(weights, Mapping):
            unknown = set(weights) - set(tickers)
            if unknown:
                raise KeyError(f"weights for tickers not in this set: {sorted(unknown)}")
            w = np.array([float(weights.get(t, 0.0)) for t in tickers])
        else:
            w = np.asarray(list(weights), dtype=float)
            if w.shape != (len(tickers),):
                raise ValueError(f"expected {len(tickers)} weights, got {w.shape}")
        if np.any(w < 0):
            raise ValueError("weights must be non-negative (long-only prototype)")
        if not np.isfinite(w).all() or w.sum() <= 0:
            raise ValueError("weights must be finite and sum to a positive number")
        return w / w.sum()

    def portfolio(self, weights=None, label: str | None = None) -> "Portfolio":
        """A Portfolio over this set.

        weights: None (equal weights), {ticker: weight} (missing = 0),
                 a Series, or a sequence in ticker order.  Normalized to
                 sum to 1; must be non-negative.
        """
        return Portfolio(self, self._as_weight_array(weights), label=label)

    def equal_weight(self) -> "Portfolio":
        return self.portfolio(None, label="Equal weights")

    def _require_pair(self) -> None:
        if len(self) < 2:
            raise ValueError("optimization needs at least two assets")

    def min_vol(self) -> "Portfolio":
        """Minimum-dispersion portfolio."""
        self._require_pair()
        w = _solve(self.expected_returns, self.risk_matrix, "min_volatility")
        return Portfolio(self, w, label="Min dispersion")

    def tangency(self, risk_free_rate: float) -> "Portfolio | None":
        """Max-Sharpe portfolio, or None if no asset beats the risk-free rate."""
        self._require_pair()
        if float(self.expected_returns.max()) <= risk_free_rate:
            return None
        w = _solve(self.expected_returns, self.risk_matrix, "max_sharpe",
                   risk_free_rate=risk_free_rate)
        return Portfolio(self, w, label="Tangency")

    def efficient_return(self, target_return: float) -> "Portfolio":
        """Min-dispersion portfolio achieving a target expected return."""
        self._require_pair()
        w = _solve(self.expected_returns, self.risk_matrix, "efficient_return",
                   target_return=float(target_return))
        return Portfolio(self, w, label=f"Target return {target_return:.4f}")

    def efficient_risk(self, target_dispersion: float) -> "Portfolio":
        """Max-return portfolio at a target dispersion."""
        self._require_pair()
        w = _solve(self.expected_returns, self.risk_matrix, "efficient_risk",
                   target_volatility=float(target_dispersion))
        return Portfolio(self, w, label=f"Target dispersion {target_dispersion:.4f}")

    def frontier(self, risk_free_rate: float = 0.02,
                 n_points: int = N_FRONTIER_POINTS) -> "Frontier":
        return Frontier(self, risk_free_rate=risk_free_rate, n_points=n_points)

    # -- composition: portfolios as members ------------------------------
    @classmethod
    def from_members(cls, members: Iterable, method: str = "normal",
                     names: Mapping[str, str] | None = None, *,
                     metric: str = "relative", timeframe: str = "D",
                     samp_int: int | None = None,
                     basis: str = "arithmetic") -> "AssetSet":
        """Build a set whose members are prices Series and/or Portfolios.

        A Portfolio contributes its `value_index` (a prices-like series
        named by its label), so nested portfolios are first-class assets.
        Members are inner-joined on date.  The return-calculation options
        apply to the *outer* set: a nested portfolio's own options shaped
        its `value_index`, and the outer set re-estimates from there.
        """
        cols = []
        for m in members:
            if isinstance(m, Portfolio):
                cols.append(m.value_index)
            elif isinstance(m, pd.Series):
                if m.name is None:
                    raise ValueError("prices Series members must be named")
                cols.append(m)
            elif isinstance(m, pd.DataFrame):
                cols.extend(m[c] for c in m.columns)
            else:
                raise TypeError(f"unsupported member type: {type(m).__name__}")
        prices = pd.concat(cols, axis=1, join="inner")
        return cls(prices, method=method, names=names, metric=metric,
                   timeframe=timeframe, samp_int=samp_int, basis=basis)

    # -- the Explorer payload (what compute_analysis returns) -----------
    def analysis(self, weights: Mapping[str, float] | None = None,
                 risk_free_rate: float = 0.02,
                 n_points: int = N_FRONTIER_POINTS, *,
                 metric: str | None = None, timeframe: str | None = None,
                 samp_int=_UNSET, basis: str | None = None) -> dict:
        """Everything the Explorer UI needs, as one plain dict.

        Lenient at the boundary: unknown tickers in `weights` are ignored,
        negatives are clipped to 0, and an all-zero/empty weighting falls
        back to equal weights (matches the original procedural API).

        The return-calculation options default to this set's own; naming
        one runs the analysis on `with_options(...)` instead.
        """
        override = self.with_options(metric=metric, timeframe=timeframe,
                                     samp_int=samp_int, basis=basis)
        if override is not self:
            return override.analysis(weights, risk_free_rate, n_points)

        if weights:
            clean = {t: max(0.0, float(weights.get(t, 0.0))) for t in self.tickers}
            if sum(clean.values()) <= 0:
                clean = None
        else:
            clean = None
        mine = self.portfolio(clean, label="Your choice")

        result: dict = {
            "tickers": self.tickers,
            "method": self.method,
            "risk_free_rate": risk_free_rate,
            "assets": self.asset_points(),
            "start": self.start,
            "end": self.end,
            "n_days": self.n_days,
            "portfolio": mine.to_dict(risk_free_rate),
        }
        result.update(self.frontier(risk_free_rate, n_points).to_dict())
        return result


# ----------------------------------------------------------------------
# Portfolio
# ----------------------------------------------------------------------
class Portfolio:
    """Weights over an AssetSet.  Has-an AssetSet; behaves like an asset.

    Construct via `AssetSet.portfolio(...)` (validates/normalizes weights).
    """

    def __init__(self, asset_set: AssetSet, weights: np.ndarray,
                 label: str | None = None):
        self.asset_set = asset_set
        self._w = np.asarray(weights, dtype=float)
        self.label = label or "Portfolio"

    # -- identity -------------------------------------------------------
    @property
    def tickers(self) -> list[str]:
        return self.asset_set.tickers

    @property
    def weights(self) -> pd.Series:
        return pd.Series(self._w, index=self.tickers, name="weight")

    @property
    def weight_array(self) -> np.ndarray:
        return self._w.copy()

    def __repr__(self) -> str:
        held = {t: round(float(w), 4) for t, w in zip(self.tickers, self._w) if w > 1e-5}
        return (f"Portfolio({self.label!r}, {held}, "
                f"ret={self.expected_return:.4f}, disp={self.dispersion:.4f})")

    # -- performance (engine) -------------------------------------------
    def perf(self, risk_free_rate: float = 0.0) -> dict:
        """{'ret', 'vol', 'sharpe'} — identical to the engine's `_perf`."""
        return _perf(self._w, self.asset_set.expected_returns,
                     self.asset_set.risk_matrix, risk_free_rate)

    @cached_property
    def expected_return(self) -> float:
        return self.perf()["ret"]

    @cached_property
    def dispersion(self) -> float:
        return self.perf()["vol"]

    def sharpe(self, risk_free_rate: float) -> float:
        return self.perf(risk_free_rate)["sharpe"]

    def to_dict(self, risk_free_rate: float = 0.0) -> dict:
        """UI payload shape: weights (non-trivial only) + ret/vol/sharpe."""
        return {"weights": _weights_dict(self._w, self.tickers),
                **self.perf(risk_free_rate)}

    # -- the asset-like face -------------------------------------------
    @cached_property
    def returns(self) -> pd.Series:
        """Returns of the fixed-weight (rebalanced every period) portfolio.

        One row per row of the set's return series — daily by default, but
        the set's `timeframe` / `samp_int` decide.
        """
        r = self.asset_set.returns.to_numpy(dtype=float) @ self._w
        return pd.Series(r, index=self.asset_set.returns.index, name=self.label)

    @cached_property
    def value_index(self) -> pd.Series:
        """Prices-like series: 100 at the start, then compounded growth.

        Dated on the set's return grid, with the first date backed up to
        the start of the first return window — so under the daily default
        this is exactly the prices index.
        """
        steps = stats.growth_factors(self.returns, self.asset_set.metric)
        growth = np.concatenate([[1.0], np.cumprod(steps.to_numpy())])
        return pd.Series(100.0 * growth, index=self._value_dates(),
                         name=self.label)

    def _value_dates(self) -> pd.Index:
        """`value_index` dates: first window's start, then one per return."""
        aset = self.asset_set
        idx, rets_idx = aset.prices.index, self.returns.index
        first = int(idx.get_indexer([rets_idx[0]])[0])
        start = max(first - stats.return_window(aset.timeframe), 0)
        return rets_idx.insert(0, idx[start])

    def as_asset(self) -> Asset:
        return Asset(self.label, self.label)


# ----------------------------------------------------------------------
# Frontier
# ----------------------------------------------------------------------
class Frontier:
    """The efficient frontier of an AssetSet, plus its anchor portfolios.

    points:   min-dispersion portfolio at each of `n_points` return targets
              from the min-vol return up to the best single asset
              (legacy portOpt.calc_efficient_frontier construction)
    min_vol:  minimum-dispersion portfolio
    tangency: max-Sharpe portfolio at `risk_free_rate` (None if no asset
              beats the risk-free rate)
    cal:      capital allocation line endpoints for plotting, or None

    For a single-asset set the frontier is a point: everything is empty.
    """

    def __init__(self, asset_set: AssetSet, risk_free_rate: float = 0.02,
                 n_points: int = N_FRONTIER_POINTS):
        self.asset_set = asset_set
        self.risk_free_rate = float(risk_free_rate)
        self.n_points = int(n_points)
        self.points: list[Portfolio] = []
        self.min_vol: Portfolio | None = None
        self.tangency: Portfolio | None = None
        if len(asset_set) >= 2:
            self._compute()

    def _compute(self) -> None:
        aset, rf = self.asset_set, self.risk_free_rate
        self.min_vol = aset.min_vol()
        self.tangency = aset.tangency(rf)
        lo, hi = self.min_vol.expected_return, float(aset.expected_returns.max())
        for i, target in enumerate(np.linspace(lo, hi, self.n_points)):
            try:
                p = aset.efficient_return(float(target))
            except Exception:
                continue  # infeasible edge targets are fine to skip
            p.label = f"Frontier point {i}"
            self.points.append(p)

    # -- container face -------------------------------------------------
    def __len__(self) -> int:
        return len(self.points)

    def __iter__(self) -> Iterator[Portfolio]:
        return iter(self.points)

    def __getitem__(self, i) -> Portfolio:
        return self.points[i]

    def __repr__(self) -> str:
        return (f"Frontier({len(self)} points, rf={self.risk_free_rate}, "
                f"tangency={'yes' if self.tangency else 'none'})")

    # -- pick any point on the curve ------------------------------------
    def at_return(self, target_return: float) -> Portfolio:
        """Exact frontier portfolio at a target expected return."""
        return self.asset_set.efficient_return(target_return)

    def at_dispersion(self, target_dispersion: float) -> Portfolio:
        """Exact frontier portfolio at a target dispersion."""
        return self.asset_set.efficient_risk(target_dispersion)

    def nearest(self, expected_return: float | None = None,
                dispersion: float | None = None) -> Portfolio:
        """Closest pre-computed point to a return or dispersion (no solve)."""
        if not self.points:
            raise ValueError("frontier has no points")
        if (expected_return is None) == (dispersion is None):
            raise ValueError("give exactly one of expected_return / dispersion")
        key = ((lambda p: abs(p.expected_return - expected_return))
               if expected_return is not None
               else (lambda p: abs(p.dispersion - dispersion)))
        return min(self.points, key=key)

    # -- plotting helpers / payload ------------------------------------
    @property
    def curve(self) -> pd.DataFrame:
        """(dispersion, expected_return) per point, for plotting."""
        return pd.DataFrame({"dispersion": [p.dispersion for p in self.points],
                             "expected_return": [p.expected_return for p in self.points]})

    @property
    def cal(self) -> dict | None:
        """Capital allocation line endpoints {x: [..], y: [..]}."""
        if self.tangency is None:
            return None
        rf = self.risk_free_rate
        vols = [p.dispersion for p in self.points] + \
               [a["vol"] for a in self.asset_set.asset_points()]
        x_end = max(vols or [self.tangency.dispersion]) * 1.05
        return {"x": [0.0, x_end],
                "y": [rf, rf + self.tangency.sharpe(rf) * x_end]}

    def to_dict(self) -> dict:
        rf = self.risk_free_rate
        return {
            "min_vol": self.min_vol.to_dict(rf) if self.min_vol else None,
            "tangency": self.tangency.to_dict(rf) if self.tangency else None,
            "frontier": [p.to_dict(rf) for p in self.points],
            "cal": self.cal,
        }
