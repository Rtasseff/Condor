"""Stability engine: how much would the best mix move on a different history?

Pure functions for a block-bootstrap diagnostic on the tangency weights.
The model (`AssetSet.stability`) rebuilds the set from each resample and
re-runs its *own* estimators and solver; nothing here estimates or
optimizes.

    block_indices(n, block, rng)       row indices of one resample
    split_block_indices(...)           the same, with a younger proxy's rows kept apart
    resample_prices(prices, idx)       prices rebuilt from resampled returns
    align_reference / resample_reference  an outside market proxy on the same rows
    resample_series(values, dates, idx) a daily series (T-bill) on the same rows
    summarize(weights, tickers, ...)   p10 / p50 / p90 and held share per asset

One resample is one index array and it is applied to *every* asset and to
the T-bill, so cross-asset co-movement and the premium over T-bills survive
the reshuffle; only the order of the history changes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_BLOCK = 21        # the forecast's block length (about a month)
HELD_THRESHOLD = 0.01     # a weight above 1% counts as "held"
PERCENTILES = (10, 50, 90)


def block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Row indices for one moving-block resample of `n` rows.

    Contiguous blocks of `block` rows (a shorter one if n < block) start at
    uniformly random positions; blocks are concatenated and the last is cut,
    so exactly `n` indices come back.
    """
    if n < 1:
        raise ValueError("need at least one row to resample")
    if block < 1:
        raise ValueError("block must be >= 1")
    block = min(int(block), n)
    n_blocks = -(-n // block)
    starts = rng.integers(0, n - block + 1, n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]).ravel()
    return idx[:n]


def split_block_indices(n: int, block: int, rng: np.random.Generator,
                        first_valid: int = 0) -> np.ndarray:
    """`block_indices`, drawn separately before and from `first_valid` on.

    A market proxy that starts after the set only exists from row
    `first_valid`; keeping the later rows' draws among the later rows
    means every resampled row there has a proxy return, as in the original
    run.  `first_valid=0` is plain `block_indices`.
    """
    if first_valid <= 0 or first_valid >= n:
        return block_indices(n, block, rng)
    return np.concatenate([
        block_indices(first_valid, block, rng),
        first_valid + block_indices(n - first_valid, block, rng)])


def align_reference(ref: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """The proxy's prices on `index`: forward-filled, missing before it starts."""
    r = ref.dropna().sort_index()
    return r.reindex(r.index.union(index)).ffill().reindex(index)


def resample_reference(aligned: pd.Series, idx: np.ndarray) -> pd.Series:
    """The proxy rebuilt from the same rows as the assets.

    `aligned` is `align_reference(...)` on the prices' index and `idx` the
    resample of its `len(aligned) - 1` daily rows, drawn with
    `split_block_indices(..., first_valid)`.  The result starts at the
    proxy's first date and covers only the dates from there on, each return
    coming from the row the assets drew, so a join with the resampled
    prices sees the same rows the original run does.
    """
    idx = np.asarray(idx)
    first = aligned.first_valid_index()
    if first is None:
        raise ValueError("the market proxy has no prices in this window")
    f = aligned.index.get_loc(first)
    rr = aligned.pct_change().iloc[1:].to_numpy(dtype=float)
    if idx.shape != (len(rr),):
        raise ValueError(f"expected {len(rr)} indices, got {idx.shape}")
    grown = 100.0 * np.cumprod(1.0 + rr[idx[f:]])
    return pd.Series(np.concatenate([[100.0], grown]),
                     index=aligned.index[f:], name=aligned.name)


def resample_prices(prices: pd.DataFrame, idx: np.ndarray) -> pd.DataFrame:
    """Prices rebuilt from the daily returns picked by `idx`.

    `idx` indexes the `len(prices) - 1` daily return rows.  The result keeps
    the original dates and first row, so the window length and calendar span
    are unchanged; `range(len(prices) - 1)` reproduces `prices`.
    """
    idx = np.asarray(idx)
    rets = prices.pct_change().iloc[1:].to_numpy(dtype=float)
    if idx.shape != (len(rets),):
        raise ValueError(f"expected {len(rets)} indices, got {idx.shape}")
    grown = prices.iloc[0].to_numpy(dtype=float) * np.cumprod(
        1.0 + rets[idx], axis=0)
    out = np.vstack([prices.iloc[0].to_numpy(dtype=float), grown])
    return pd.DataFrame(out, index=prices.index, columns=prices.columns)


def resample_series(values: pd.Series, dates: pd.DatetimeIndex,
                    idx: np.ndarray) -> pd.Series:
    """A daily series (e.g. T-bill yield) on the resample's rows.

    `values` is forward-filled (back-filled for a leading gap) onto the
    return dates `dates` (the prices' index without its first date), then
    row `idx[k]` is placed at date `k` -- the same rows the prices drew.
    """
    y = values.dropna().sort_index()
    y = y.groupby(level=0).last()
    aligned = (y.reindex(y.index.union(dates)).ffill()
                .reindex(dates).bfill())
    return pd.Series(aligned.to_numpy()[np.asarray(idx)], index=dates,
                     name=values.name)


def summarize(weights: list[np.ndarray], tickers: list[str]) -> dict:
    """Per-asset p10 / p50 / p90 of the weights, plus the held share.

    `weights` is one array per *successful* resample (fractions summing to
    1).  `held_share` is the share of those resamples in which the asset's
    weight exceeds 1%.  With no successful resample every number is None.
    """
    if not weights:
        return {t: {"p10": None, "p50": None, "p90": None, "held_share": None}
                for t in tickers}
    w = np.vstack(weights)
    q = np.percentile(w, PERCENTILES, axis=0)
    held = (w > HELD_THRESHOLD).mean(axis=0)
    return {t: {"p10": float(q[0, i]), "p50": float(q[1, i]),
                "p90": float(q[2, i]), "held_share": float(held[i])}
            for i, t in enumerate(tickers)}
