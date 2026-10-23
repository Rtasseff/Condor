# 0005 — Ledger v2: cost basis, income, currency, bills, mirrors

Date: 2026-10-23. Status: accepted. Reopens and extends
[0004](0004-account-ledger.md) under its own "reopens if" clauses
(real brokerage import; multi-currency or fixed-income positions).

## Context

RT's real two-bucket portfolio (a USD ETF account at a broker, a EUR
account of Spanish Letras del Tesoro) is kept in its own repo as a CSV
ledger, which stays the record. RT wants Condor as an add-on view of
it — a local, read-only mirror — and wants that portfolio to drive
Condor's account features. The ledger needs things ADR 0004 left out:
average cost and realized gain, income and fee events that are return
(not contributions), one currency per account, zero-coupon bills with
no ticker, and a one-way import. Exchange format v1 was agreed with
that repo's session on 2026-10-23 (its `docs/condor.md`; restated in
`docs/LEDGER-FORMAT.md` here).

## Decision

1. **The ledger grows four kinds and two columns.** Kinds `dividend`,
   `interest`, `fee`, `redeem`; event columns `fees` (≥ 0, default 0)
   and `maturity` (date, bills only). Old six-column ledgers replay
   unchanged.
2. **Income and fees are return, never contributions.** Dividends and
   interest raise cash by gross − fees (income is recorded gross);
   standalone fees lower cash. None is a flow, so TWR sees them as
   return — the reason logging income as a deposit was wrong.
3. **Average cost.** Buy fees go into cost; a sell (or redeem) removes
   avg × qty from cost and realizes net proceeds − avg × qty. A
   `set_shares` force in brings cost at the recorded price; a force out
   realizes at the recorded price (it is an in-kind withdrawal), which
   keeps the reconciliation identity exact:
   `value = contributions + realized + unrealized + income − charges`
   (charges = standalone fees + fees withheld from income; trade fees
   already live inside cost and realized).
4. **One currency per account; no FX in the ledger.** Every amount in
   an account is in its currency; the engine is currency-agnostic and
   the UI labels money with the account's ISO code. A combined
   base-currency total (daily FX) is deferred to the account-plans
   bucket.
5. **Bills are lots that accrete in a straight line.** A buy carrying a
   `maturity` makes its ticker a bill (format: `LETRA-YYYY-MM-DD`).
   Each lot's value runs linearly from cost on its settlement date to
   nominal at maturity, then holds at nominal; partial disposals scale
   every lot pro rata (consistent with average cost). `redeem` pays
   nominal × 1 − fees. Bills never touch the price store. Straight line
   was chosen over constant yield: on a 12-month bill at ~3% the two
   differ by ≈0.22 per 1,000 nominal at mid-life and agree at maturity.
6. **Imported accounts are read-only mirrors.** `Account` gains
   `label` (the format's account label), `currency`, `mirror`,
   `imported_at`. `manage.py import_ledger … --replace` fully replaces
   each labelled account's events (and targets, when given) in one
   transaction; Condor never writes back, and the web refuses every
   write to a mirror. Parsing/validation is a pure module
   (`condor/ledger_io.py`); the command only persists.
7. **Many accounts in the UI.** The page and every `/api/account*`
   endpoint take `?account=<uuid>`; without it they use the default
   account (first non-mirror, else first). ADR 0004 §4 anticipated
   this.

## Alternatives rejected

- *Redeem as `sell` at 1:* loses the maturity check and the meaning;
  `sell` stays free for an early sale at market.
- *Constant-yield accretion:* more machinery for sub-euro differences.
- *Per-lot (FIFO) cost basis:* the source ledger is average-cost;
  lot-level tax work reopens this (see below).
- *Merging imports by row identity:* the source has no stable row IDs
  and is the record; full replace is always safe and boring.
- *Per-(account, ccy) cash buckets with FX rows:* not needed while each
  account holds one currency.

## Reopens if

- An account must hold two currencies, or FX conversions happen inside
  an account.
- Tax lot selection (FIFO / specific ID) is needed.
- Coupon bonds, or bills priced by market rather than by accretion.
- Two-way sync (Condor as a source of truth for any imported account).
