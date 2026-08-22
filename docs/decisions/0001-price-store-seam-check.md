# ADR 0001 — Price store keeps adjusted closes, verified by a seam check

Date: 2026-08-22 · Status: accepted

## Context

The analytics consume *adjusted* closes (splits + dividends folded in, so
daily percent changes are total returns). Adjusted series are **not
append-only**: every split or dividend rewrites the entire past series.
A store that naively appends "new rows since last date" silently corrupts
history at the first corporate action — the classic home-rolled-price-store
bug.

## Decision

Store the adjusted series, and make incremental updates safe with a
**seam check** (`condor/data/store.py`): re-fetch a short overlap window
(20 stored rows), compare against what's on disk (rtol 2e-3 for provider
rounding). Match → append the genuinely new rows. Mismatch → a corporate
action (or provider revision) happened → re-download the ticker's full
history and replace the file. At daily/personal scale a full history is
~100 KB per ticker-decade, so the "penalty" path costs nothing.

## Alternative considered: raw prices + corporate-action events

The textbook design: store raw closes plus dividend/split events
(genuinely append-only) and compute adjusted series on read. Rejected for
now — meaningful extra code (adjustment math, per-source actions
fetching, more tests) to avoid a re-download we can afford, and sources
disagree about actions data more than they disagree about adjusted
closes. **This is the upgrade path** if any of these ever become true:

- intraday data (full re-fetch stops being cheap),
- large universes (hundreds of tickers × frequent refetches),
- a need to audit adjustments themselves (show dividend history, verify
  a provider's adjustment math).

## Consequences

- Updates are cheap and drift is impossible rather than merely unlikely.
- A provider *revision* of history (not just a corporate action) also
  triggers the refetch path — that's the correct behaviour.
- The store records provenance per ticker (source, fetched-at, span) in
  `manifest.json`; "data as of" is `PriceStore.as_of(ticker)`.
