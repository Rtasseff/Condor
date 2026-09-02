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
from . import forecast as _forecast_engine
from .stats import annual_factor
from .frontier import (N_CAL_POINTS, N_FRONTIER_POINTS, _cal_mix, _perf,
                       _solve, _weights_dict)

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

    def forecast(self, horizon_years: float = 2,
                 levels=_forecast_engine.DEFAULT_LEVELS, *,
                 cash_weight: float = 0.0,
                 risk_free_rate: float = 0.0,
                 model: str = "steady",
                 block: int = 21, n_paths: int = 10_000,
                 seed: int = 0, anchor: str = "historical",
                 anchor_value: float | None = None) -> "Forecast":
        """Project this portfolio's wealth forward (research rung A):
        closed-form constant-rate ("GBM") bands, plus a second band set
        with the drift's own estimation error folded in. A non-zero
        `cash_weight` forecasts the *complete* portfolio — this risky
        mix constant-mixed with cash earning `risk_free_rate` — so a
        CAL point or a real account (holdings + cash) forecasts whole.
        `model` picks the rung: "steady" (closed form) or "bootstrap"
        (rung B — stationary 21-day-block resampling of the actual
        history, guard-railed to never show narrower bands than the
        closed form). `anchor` (rung C) chooses what the centre of the
        fan assumes: "historical" (this mix's own sample mean, the
        default and an exact no-op), "market" (a long-run anchor) or
        "custom" with `anchor_value` an annual simple return; either
        anchor is blended with the sample mean by precision, never
        substituted for it. Numbers come from the engine."""
        return Forecast(self, horizon_years=horizon_years, levels=levels,
                        cash_weight=cash_weight,
                        risk_free_rate=risk_free_rate, model=model,
                        block=block, n_paths=n_paths, seed=seed,
                        anchor=anchor, anchor_value=anchor_value)

    def as_asset(self) -> Asset:
        return Asset(self.label, self.label)


# ----------------------------------------------------------------------
# Forecast
# ----------------------------------------------------------------------
def _resolve_anchor(anchor: str,
                    anchor_value: float | None) -> tuple[float | None,
                                                         float | None]:
    """Anchor mode -> (annual simple anchor, prior sd), or (None, None)
    for "historical", which is the identity: no blend happens at all.

    The long-run market number is a documented constant, not a live
    feed (`condor/forecast.py`); a custom anchor is the user's own
    number, held with the same default confidence so the fan keeps an
    honest estimate-error band around it.
    """
    if anchor == "historical":
        return None, None
    if anchor == "market":
        return _forecast_engine.MARKET_ANCHOR, _forecast_engine.ANCHOR_PRIOR_SD
    if anchor_value is None:
        raise ValueError("a custom anchor needs anchor_value")
    value = float(anchor_value)
    lo, hi = _forecast_engine.ANCHOR_MIN, _forecast_engine.ANCHOR_MAX
    if not lo <= value <= hi:
        raise ValueError(f"anchor_value must be between {lo} and {hi}")
    return value, _forecast_engine.ANCHOR_PRIOR_SD


class Forecast:
    """A portfolio's forward fan chart — the simplest model, honestly.

    Closed-form lognormal bands from the portfolio's per-period log
    returns (engine: `condor/forecast.py`), in two nested sets:
    path-only ("market randomness") and with the expected return's own
    estimation error (`_est` — the dominant term at multi-year
    horizons; see docs/research/forecast-methods-ladder.md).

    `table` is a DataFrame indexed by horizon (years): `median`,
    `lo65/hi65/lo95/hi95` and their `_est` twins, all wealth multiples
    of 1 (row 0 = today = 1.0). `to_dict()` is the UI payload.

    The centre of the fan is an assumption, and `anchor` is where the
    user states it: "historical" leaves the sample mean alone, while
    "market"/"custom" blend it with a long-run anchor by precision
    (rung C). Everything downstream — median, both band sets, the
    headline rate and its error bar — then reports the anchored
    posterior; `mu_historical` keeps what the sample alone said, so the
    UI can show the user what their choice moved.
    """

    MODELS = {"steady": "constant-rate", "bootstrap": "block-bootstrap"}
    MODEL = "constant-rate"  # rung A's payload name (kept stable)
    ANCHORS = ("historical", "market", "custom")

    def __init__(self, portfolio: "Portfolio", horizon_years: float = 2,
                 levels=_forecast_engine.DEFAULT_LEVELS,
                 cash_weight: float = 0.0, risk_free_rate: float = 0.0,
                 model: str = "steady", block: int = 21,
                 n_paths: int = 10_000, seed: int = 0,
                 anchor: str = "historical",
                 anchor_value: float | None = None):
        if not 0 < float(horizon_years) <= 50:
            raise ValueError("horizon_years must be in (0, 50]")
        if model not in self.MODELS:
            raise ValueError(f"model must be one of {sorted(self.MODELS)}")
        if anchor not in self.ANCHORS:
            raise ValueError(f"anchor must be one of {list(self.ANCHORS)}")
        self.portfolio = portfolio
        self.horizon_years = float(horizon_years)
        self.levels = tuple(levels)
        self.cash_weight = float(cash_weight)
        self.risk_free_rate = float(risk_free_rate)
        self.model = self.MODELS[model]
        self.block = int(block) if model == "bootstrap" else None
        self.n_paths = int(n_paths) if model == "bootstrap" else None
        self.guarded = False
        self.periods_per_year = annual_factor(portfolio.asset_set.timeframe)
        returns = portfolio.returns
        if self.cash_weight:   # complete portfolio: risky + cash sleeve
            returns = _forecast_engine.blend_with_cash(
                returns, self.cash_weight, self.risk_free_rate,
                self.periods_per_year)
        self.m, self.s, self.n_obs = _forecast_engine.log_moments(returns)
        self.m_hist = self.m               # what the sample alone said
        self.anchor = anchor
        self.anchor_value, self.anchor_prior_sd = _resolve_anchor(
            anchor, anchor_value)
        # An anchor is an assumption about the *risky* market, so on a
        # complete portfolio it applies to the risky sleeve only: the
        # cash sleeve is known to earn rf, and a constant mix blends
        # expectations (and the width of a belief about them) linearly.
        self.anchor_effective = self.anchor_prior_sd_effective = None
        self.drift_sd = None
        if self.anchor_value is not None:
            risky = 1.0 - self.cash_weight
            self.anchor_effective = (risky * self.anchor_value
                                     + self.cash_weight * self.risk_free_rate)
            self.anchor_prior_sd_effective = risky * self.anchor_prior_sd
            self.m, self.drift_sd = _forecast_engine.anchored_log_drift(
                self.m, self.s, self.n_obs, self.periods_per_year,
                self.anchor_effective, self.anchor_prior_sd_effective)
        step = 5 if self.periods_per_year >= 252 else 1
        horizon = int(round(self.horizon_years * self.periods_per_year))
        closed = _forecast_engine.lognormal_bands(
            self.m, self.s, self.n_obs, horizon_periods=horizon,
            periods_per_year=self.periods_per_year,
            levels=self.levels, step=step, drift_sd=self.drift_sd)
        if model == "bootstrap":
            boot = _forecast_engine.bootstrap_bands(
                returns, horizon_periods=horizon,
                periods_per_year=self.periods_per_year,
                levels=self.levels, step=step, block=self.block,
                n_paths=self.n_paths, seed=int(seed),
                drift_shift=self.m - self.m_hist, drift_sd=self.drift_sd)
            # research guard rail: resampling one lucky decade must not
            # present narrower uncertainty than the closed form admits
            self.table, self.guarded = _forecast_engine.band_floor(
                boot, closed)
        else:
            self.table = closed

    # -- annualized headline numbers (for honest labeling) --------------
    @property
    def mu_annual(self) -> float:
        """Geometric annual growth rate implied by the median path."""
        return float(np.exp(self.m * self.periods_per_year) - 1)

    @property
    def sigma_annual(self) -> float:
        return float(self.s * np.sqrt(self.periods_per_year))

    @property
    def mu_se_annual(self) -> float:
        """Uncertainty in the annualized log growth rate (≈ points of
        annual return). Unanchored this is the sample SE, which depends
        only on the calendar span (Merton); anchored it is the posterior
        sd, which is smaller because a second source of information was
        brought in."""
        if self.drift_sd is not None:
            return float(self.drift_sd * self.periods_per_year)
        return _forecast_engine.mu_standard_error(
            self.s, self.n_obs, self.periods_per_year)

    @property
    def mu_historical(self) -> float:
        """Geometric annual growth rate the sample alone implies —
        `mu_annual` when the anchor is "historical"."""
        return float(np.exp(self.m_hist * self.periods_per_year) - 1)

    @property
    def mu_se_historical(self) -> float:
        """The sample SE, whatever the anchor: what the history on its
        own could tell us about the rate."""
        return _forecast_engine.mu_standard_error(
            self.s, self.n_obs, self.periods_per_year)

    @property
    def mu_ci95(self) -> tuple[float, float]:
        """95% CI on the geometric annual growth rate."""
        drift = self.m * self.periods_per_year
        half = 1.959964 * self.mu_se_annual
        return (float(np.exp(drift - half) - 1),
                float(np.exp(drift + half) - 1))

    @property
    def span_years(self) -> float:
        return self.n_obs / self.periods_per_year

    def __repr__(self) -> str:
        anchored = "" if self.anchor == "historical" else f", {self.anchor}-anchored"
        return (f"Forecast({self.portfolio.label!r}, {self.horizon_years}y, "
                f"mu={self.mu_annual:.3f}±{self.mu_se_annual:.3f}/yr"
                f"{anchored})")

    def to_dict(self) -> dict:
        t = self.table
        r6 = lambda a: [round(float(x), 6) for x in a]
        bands, bands_est = [], []
        for lvl in self.levels:
            tag = str(int(round(100 * lvl)))
            bands.append({"level": int(tag),
                          "lo": r6(t[f"lo{tag}"]), "hi": r6(t[f"hi{tag}"])})
            bands_est.append({"level": int(tag),
                              "lo": r6(t[f"lo{tag}_est"]),
                              "hi": r6(t[f"hi{tag}_est"])})
        lo_ci, hi_ci = self.mu_ci95
        r6opt = lambda x: None if x is None else round(float(x), 6)
        return {
            "model": self.model,
            "anchor": {
                # what the centre of this fan assumes, and where it came from
                "mode": self.anchor,
                "value": r6opt(self.anchor_value),
                "prior_sd": r6opt(self.anchor_prior_sd),
                "effective": r6opt(self.anchor_effective),
                "prior_sd_effective": r6opt(self.anchor_prior_sd_effective),
                "mu_historical": round(self.mu_historical, 6),
                "mu_se_historical": round(self.mu_se_historical, 6),
            },
            "block": self.block,
            "n_paths": self.n_paths,
            "guarded": self.guarded,
            "horizon_years": self.horizon_years,
            "cash_weight": round(self.cash_weight, 6),
            "risk_free_rate": round(self.risk_free_rate, 6),
            "t": r6(t.index),
            "median": r6(t["median"]),
            "bands": bands,          # market randomness only
            "bands_est": bands_est,  # + estimation error in the drift
            "mu_annual": round(self.mu_annual, 6),
            "mu_se_annual": round(self.mu_se_annual, 6),
            "mu_ci95": [round(lo_ci, 6), round(hi_ci, 6)],
            "sigma_annual": round(self.sigma_annual, 6),
            "n_obs": self.n_obs,
            "span_years": round(self.span_years, 3),
        }


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

    def cal_mix(self, risky_fraction: float) -> dict:
        """A point on the capital allocation line, as a payload dict.

        `risky_fraction` of wealth goes into the tangency portfolio and
        the rest into T-bills at the risk-free rate; a fraction above 1
        means borrowing at that rate (flagged `borrowing` -- most
        investors can't actually borrow at the T-bill rate).  Weights are
        fractions of *total* wealth, so they sum to `risky_fraction`;
        `cash_frac` is the balance (negative when borrowing).  Numbers
        come from the engine's `_cal_mix`; Sharpe is None at zero risk
        (NaN is not JSON-safe).
        """
        if self.tangency is None:
            raise ValueError("no tangency portfolio at this risk-free rate")
        k = float(risky_fraction)
        if k < 0:
            raise ValueError("risky_fraction must be >= 0")
        perf = _cal_mix(k, self.risk_free_rate,
                        self.tangency.expected_return, self.tangency.dispersion)
        if perf["vol"] == 0:
            perf["sharpe"] = None
        return {
            "risky_frac": round(k, 6),
            "cash_frac": round(1.0 - k, 6),
            "borrowing": k > 1 + 1e-9,
            "weights": _weights_dict(k * self.tangency.weight_array,
                                     self.asset_set.tickers),
            **perf,
        }

    # -- plotting helpers / payload ------------------------------------
    @property
    def curve(self) -> pd.DataFrame:
        """(dispersion, expected_return) per point, for plotting."""
        return pd.DataFrame({"dispersion": [p.dispersion for p in self.points],
                             "expected_return": [p.expected_return for p in self.points]})

    @property
    def cal(self) -> dict | None:
        """Capital allocation line: endpoints for drawing the line, plus
        a grid of two-fund mixes (`cal_mix`) from 100% T-bills out past
        the tangency into the borrowing region, for the UI to snap to."""
        if self.tangency is None:
            return None
        rf = self.risk_free_rate
        vols = [p.dispersion for p in self.points] + \
               [a["vol"] for a in self.asset_set.asset_points()]
        x_end = max(vols or [self.tangency.dispersion]) * 1.05
        k_max = x_end / self.tangency.dispersion
        return {"x": [0.0, x_end],
                "y": [rf, rf + self.tangency.sharpe(rf) * x_end],
                "points": [self.cal_mix(float(k))
                           for k in np.linspace(0.0, k_max, N_CAL_POINTS)]}

    def to_dict(self) -> dict:
        rf = self.risk_free_rate
        return {
            "min_vol": self.min_vol.to_dict(rf) if self.min_vol else None,
            "tangency": self.tangency.to_dict(rf) if self.tangency else None,
            "frontier": [p.to_dict(rf) for p in self.points],
            "cal": self.cal,
        }
