# Ledger exchange format v1.1

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

Header, exactly: `account,ticker,weight` (v1) or
`account,ticker,weight,timing,line` (v1.1). Weights are fractions of the
account's total value, each in [0, 1], summing to ≤ 1 per account (cash
is the remainder). Tickers are exchange tickers (no bills). Importing
with `--targets` replaces the targets of every account in the ledger
file; an account with no rows ends up with no targets.

- `timing` (v1.1, optional): `dca`, `lump`, `reservoir`, or empty (a
  plain setpoint with no pay-in role). At most one `reservoir` ticker
  per account; a pay-in needs at least one `dca` ticker.
- `line` (v1.1, optional): a group key `[a-z0-9_]{1,40}`, default = the
  ticker lowercased. Drift and pay-in progress are judged per line
  (e.g. RT's uranium line is URNM + DNN at 10%).

## `payin.csv` (v1.1)

Header, exactly: `account,total,date`. One row per tranche, N = rows per
account. `total` (> 0, account currency) is the same on every row of
an account. Dates are ISO, strictly increasing, the trading days the
buys execute (the source rolls weekends forward); **future dates are
allowed** (it is a plan). Importing with `--payin` replaces the plan of
every account in the ledger file.

## `rules.csv` (v1.1)

Header, exactly: `account,id,rule,ticker,threshold,action,tranches,target`.

| Column | Rule |
|---|---|
| `id` | `[a-z0-9_]{1,40}`, unique per account |
| `rule` | `below_52w_high` · `below_avg_cost` · `drift` |
| `ticker` | required for `below_52w_high` (an index or fund, e.g. `^GSPC`) and `below_avg_cost` (a held ticker); empty for `drift` |
| `threshold` | > 0: percent below the 52-week high, percent below average cost, or percentage points of drift |
| `action` | `alert` · `accelerate` |
| `tranches` | integer ≥ 1 for `accelerate`; empty for `alert` |
| `target` | empty = every `dca` line; else space-separated `dca` tickers (e.g. `URNM DNN`) |

Only rules the owner has confirmed are exported. Measures (all strict
`>` against the threshold):

- `below_52w_high` = (high − last) / high, raw closes dated after
  last date − 365 days.
- `below_avg_cost` = (avg cost − last) / avg cost; not held → not fired.
- `drift` = |line value / total − line target| per line, total including
  cash, every line checked (lump and reservoir too); muted until the
  pay-in is complete.

A fired `accelerate` with an empty target makes the buy list run
through tranche `k_due + tranches` (capped at N); with tickers, those
tickers get `tranches` extra. Advisory only: nothing is bought.

## Examples

The synthetic fixture `tests/fixtures/ledger_sample.csv` (+
`ledger_sample_targets.csv`) has one row of every side, a fractional
buy, a partial sell and one bill (v1). `tests/fixtures/payin_sample_*.csv`
(account `broker_b`) exercises v1.1: a four-tranche pay-in with a lump,
a reservoir and a two-ticker line, three rules, the executed ledger,
and the closes to value it. Both carry hand-checked results, cross-
checked by the source repo's engine (its `docs/condor-bucket-b.md`).

## Versions

- **v1** (2026-10-23): ledger + targets.
- **v1.1** (2026-10-24): targets `timing` and `line`; `payin.csv`;
  `rules.csv`. Additive — v1 files stay valid.
