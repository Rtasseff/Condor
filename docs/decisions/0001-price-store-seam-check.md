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

## Amendment (2026-11-23): final bars only

Found on real use: at 13:29 ET on a Monday the store saved that day's
bar from the provider, which is the session in progress, as Monday's
close. A seam append never rewrites the last stored row, so whenever
the real close landed within the seam tolerance (0.2%) the mid-session
price would have stood in for it permanently, and until the next 24-hour
refresh every account, rule and broker check read it as a close (it
un-fired a drawdown rule the investor had just acted on).

- A bar is kept only once it is final: its date is before today in New
  York, or New York is past 17:00 (`SETTLE`, an hour after the US close
  for providers to settle the bar). Exchanges that close earlier are
  simply picked up at that time.
- Rows a pre-amendment fetch saved before they were final are dropped on
  the next read-for-update and replaced by the final bar.
- Freshness: besides the 24-hour TTL, a ticker whose last bar is older
  than the newest weekday close that should exist is re-checked, at most
  once an hour (`RECHECK_HOURS`), so the close appears the evening it is
  made instead of the next afternoon. Holidays cost one request per hour
  of use.
- The store's clock is one seam (`store._now`, New York time); the test
  suite pins it to after today's close (`tests/conftest.py`).
