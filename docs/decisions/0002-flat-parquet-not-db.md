# ADR 0002 — Flat Parquet files for prices, not a database

Date: 2026-08-22 · Status: accepted

## Context

The price store needs persistence, incremental updates, and slicing by
date. Candidates: flat files (CSV/Parquet), SQLite, Postgres.

## Decision

One Parquet file per ticker plus a small JSON manifest, in
`~/.condor/prices/` (outside the repo — git never sees market data;
`CONDOR_DATA_DIR` overrides the location). Parquet because it's typed,
compressed, and pandas-native (`pyarrow`); per-ticker files because the
unit of update and invalidation is the ticker.

Single writer (whoever calls `PriceStore.get`), tolerant readers — fine
at personal scale where the web app, CLI, and notebooks run on one
machine.

## When a database would earn its place (future feature, not planned)

- **Concurrent writers** — a hosted multi-user deployment where several
  requests can trigger updates simultaneously (file locking gets ugly).
- **Intraday data** — millions of rows per ticker; row-level queries.
- **Transactional metadata** — audit trails of revisions, per-user data
  entitlements.

If that day comes, `PriceStore` is the interface to keep: swap its
internals for SQLite/Postgres behind the same `get/read/info/as_of`.

Note: this is separate from Django's own database. Saved portfolios
(tickers/weights/method) belong in Django models; *prices* stay in the
store. Don't mix them.
