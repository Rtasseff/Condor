"""PriceStore: one Parquet file per ticker, plus a JSON manifest.

The store owns each ticker's full daily history; any lookback is a slice.
It lives OUTSIDE the repo (default ~/.condor/prices, override with
CONDOR_DATA_DIR) so the web app, CLI, and notebooks share one copy and
git never sees it.

Update discipline — the seam check (docs/decisions/0001):
adjusted closes are NOT append-only, because a split or dividend rewrites
the whole past series. So an incremental update re-fetches a short overlap
window and compares it against what we stored. Match -> append the new
rows. Mismatch -> a corporate action happened -> re-download the full
history (cheap: ~100 KB per ticker-decade).

Flat files, no database, on purpose: docs/decisions/0002.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from .sources import DataFetchError, get_sources

MAX_AGE_HOURS = 24.0   # don't re-hit the network more often than this
SEAM_ROWS = 20         # stored rows to re-fetch and compare on update
SEAM_RTOL = 2e-3       # providers round adjusted closes; allow ~0.2%


def default_root() -> Path:
    env = os.environ.get("CONDOR_DATA_DIR")
    return Path(env) if env else Path.home() / ".condor" / "prices"


class PriceStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root else default_root()
        self._manifest_path = self.root / "manifest.json"

    # -- manifest ----------------------------------------------------
    def _manifest(self) -> dict:
        if self._manifest_path.exists():
            return json.loads(self._manifest_path.read_text())
        return {}

    def _write_manifest(self, m: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(json.dumps(m, indent=1, sort_keys=True))

    def info(self) -> pd.DataFrame:
        """One row per stored ticker: dates covered, source, fetched-at."""
        m = self._manifest()
        cols = ["first", "last", "source", "fetched_at"]
        rows = {t: [e.get(c) for c in cols] for t, e in sorted(m.items())}
        return pd.DataFrame.from_dict(rows, orient="index", columns=cols)

    def tickers(self) -> list[str]:
        """Tickers currently held in the store."""
        return sorted(self._manifest())

    def remove(self, ticker: str) -> bool:
        """Delete a ticker's file and manifest entry. True if it existed."""
        ticker = ticker.upper()
        m = self._manifest()
        existed = ticker in m
        if existed:
            del m[ticker]
            self._write_manifest(m)
        self._path(ticker).unlink(missing_ok=True)
        return existed

    def as_of(self, ticker: str) -> str | None:
        """Last stored trading date for a ticker (the honest 'data as of')."""
        entry = self._manifest().get(ticker.upper())
        return entry["last"] if entry else None

    # -- files -------------------------------------------------------
    def _path(self, ticker: str) -> Path:
        safe = ticker.upper().replace("/", "-").replace("^", "_IDX_")
        return self.root / f"{safe}.parquet"

    def read(self, ticker: str) -> pd.DataFrame | None:
        path = self._path(ticker)
        return pd.read_parquet(path) if path.exists() else None

    def _save(self, ticker: str, frame: pd.DataFrame, source: str,
              requested_start: date) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self._path(ticker))
        m = self._manifest()
        prev = m.get(ticker.upper(), {})
        old_req = prev.get("requested_start")
        req = min(str(requested_start), old_req) if old_req else str(requested_start)
        m[ticker.upper()] = {
            "source": source,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "first": str(frame.index[0].date()),
            "last": str(frame.index[-1].date()),
            "requested_start": req,
        }
        self._write_manifest(m)

    # -- fetch/update ------------------------------------------------
    def _fetch(self, ticker: str, start: date | None, sources) -> tuple:
        errors = []
        for src in sources:
            try:
                return src.fetch(ticker, start=start), src.name
            except DataFetchError as e:
                errors.append(str(e))
        raise DataFetchError(" | ".join(errors))

    def get(self, ticker: str, start: date, source: str | None = None,
            max_age_hours: float = MAX_AGE_HOURS) -> pd.DataFrame:
        """Daily [close, adj_close] for ticker from `start`, updating if due."""
        ticker = ticker.upper()
        sources = get_sources(source)
        entry = self._manifest().get(ticker)
        stored = self.read(ticker)

        needs_full = stored is None or entry is None
        if not needs_full and source is not None and entry["source"] != source:
            needs_full = True  # explicit source switch: don't mix providers
        if not needs_full and str(start) < entry["requested_start"] \
                and str(start) < entry["first"]:
            needs_full = True  # asked for earlier history than ever before

        if needs_full:
            frame, name = self._fetch(ticker, start, sources)
            self._save(ticker, frame, name, start)
            return frame.loc[str(start):]

        age_h = _age_hours(entry["fetched_at"])
        if age_h < max_age_hours:
            return stored.loc[str(start):]

        # Incremental update with seam check
        seam = stored.tail(SEAM_ROWS)
        try:
            fresh, name = self._fetch(ticker, seam.index[0].date(), sources)
        except DataFetchError:
            return stored.loc[str(start):]  # network down: serve stale, don't die
        common = seam.index.intersection(fresh.index)
        drifted = len(common) == 0 or not _close(
            seam.loc[common, "adj_close"], fresh.loc[common, "adj_close"])
        if drifted:
            frame, name = self._fetch(
                ticker, date.fromisoformat(entry["requested_start"]), sources)
        else:
            frame = pd.concat([stored, fresh.loc[fresh.index > stored.index[-1]]])
        self._save(ticker, frame, name, start)
        return frame.loc[str(start):]


def _age_hours(fetched_at_iso: str) -> float:
    fetched = datetime.fromisoformat(fetched_at_iso)
    return (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0


def _close(a: pd.Series, b: pd.Series) -> bool:
    import numpy as np
    return bool(np.allclose(a.to_numpy(), b.to_numpy(), rtol=SEAM_RTOL))
