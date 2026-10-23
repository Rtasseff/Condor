# Ledger exchange format v1

The CSV that `manage.py import_ledger` reads and `manage.py export_ledger`
writes. Agreed 2026-10-23 with the session that keeps RT's portfolio repo
(`~/projects/investments/portfolio`, its `docs/condor.md`), which
produces it with `scripts/export_condor.py`. Design: ADR
[0005](decisions/0005-ledger-v2-mirror.md). **The source repo is the
record**: an import fully replaces Condor's copy, and Condor never
writes back.

Changing this format is a two-repo change. Bump the version, and tell
that session.

## `ledger.csv`

Header, exactly: `date,account,ticker,side,qty,price,fees,ccy,maturity,note`

| Column | Rule |
|---|---|
| `date` | ISO `YYYY-MM-DD`, on or before today. Non-decreasing within each account (same-day rows keep file order, so a DEPOSIT comes before the BUY it funds). |
| `account` | Label `[a-z0-9_]{1,40}`. One Condor account per label. Never an account number. |
| `ticker` | An exchange ticker priced by daily closes; `CASH` for cash rows; a bill identifier `PREFIX-YYYY-MM-DD` (today only `LETRA-…`, a Spanish T-bill maturing that day). |
| `side` | `BUY` `SELL` `DEPOSIT` `WITHDRAW` `DIV` `INTEREST` `FEE` `REDEEM` |
| `qty` | > 0 always (the side gives direction). Shares for BUY/SELL (fractional, ≤ 6 dp); the cash amount for DEPOSIT/WITHDRAW/DIV/INTEREST/FEE; the nominal for bill rows. |
| `price` | > 0, per unit, in `ccy`. Exactly `1` for cash sides and REDEEM. For a bill BUY, the cost per 1 of nominal (e.g. `0.9706`). |
| `fees` | ≥ 0, in `ccy`. Allowed on BUY, SELL, REDEEM, DIV, INTEREST; must be `0` on DEPOSIT, WITHDRAW, FEE. |
| `ccy` | ISO 4217 (`USD`, `EUR`). One currency per account; every row of an account carries the same code. |
| `maturity` | ISO date, required on a bill BUY and equal to the date in its ticker; empty on every other row. |
| `note` | Free text, ≤ 120 chars, never an identifier (the importer refuses a run of 7+ digits). |

UTF-8, LF, `.` decimal separator, no thousands separators, no currency
symbols.

### Meaning of each side

| Side | Ticker | Cash | Contribution? | Other effects |
|---|---|---|---|---|
| DEPOSIT | `CASH` | + qty | + qty | — |
| WITHDRAW | `CASH` | − qty | − qty | — |
| BUY | security or bill | − (qty × price + fees) | no | cost += qty × price + fees |
| SELL | security or bill | + (qty × price − fees) | no | cost −= avg × qty; realized += proceeds − avg × qty |
| REDEEM | bill | + (qty × 1 − fees) | no | as SELL; dated on/after maturity; qty ≤ nominal held |
| DIV | security | + (qty − fees) | no | income += qty (gross) |
| INTEREST | `CASH` or security | + (qty − fees) | no | income += qty (gross) |
| FEE | `CASH` or security | − qty | no | charges += qty |

Income and fees are **return**, not contributions, so time-weighted
return counts them. Sells never exceed holdings and cash never goes
negative at any row.

**Bills** accrete in a straight line from cost on the settlement (row)
date to nominal on maturity, then hold at nominal. The source exporter
writes a DEPOSIT of the cost before the BUY and a WITHDRAW of the
proceeds after the REDEEM, because the money comes from and goes back
to a bank account outside the ledger.

## `targets.csv`

Header, exactly: `account,ticker,weight`. Weights are fractions of the
account's total value, each in [0, 1], summing to ≤ 1 per account (cash
is the remainder). Tickers are exchange tickers (no bills). Importing
with `--targets` replaces the targets of every account in the ledger
file; an account with no rows ends up with no targets.

## Example

The synthetic fixture `tests/fixtures/ledger_sample.csv` (+
`ledger_sample_targets.csv`) has one row of every side, a fractional
buy, a partial sell and one bill. Its hand-checked results are pinned
in `tests/test_accounting.py` and `tests/test_ledger_io.py`.
