# Real use: mirror accounts driven by a real portfolio

Since 2026-10-23 Condor's account features have been driven by one real
portfolio. Its owner keeps it in a separate repo
(`~/projects/investments/portfolio`, see its `docs/condor.md`), worked by
its own Claude session. This page is the app side of that arrangement:
who owns what, how a new export comes in, how to check it, and the
privacy rules. Format: [LEDGER-FORMAT.md](LEDGER-FORMAT.md). Designs:
ADRs [0005](decisions/0005-ledger-v2-mirror.md) (mirror ledger) and
[0007](decisions/0007-payin-rules-xirr.md) (pay-in, rules, XIRR).

## Who owns what

- **The portfolio repo is the record.** It owns the ledger, the plan,
  the rules and every investment decision: what to buy, when, and how a
  rule is read. Condor never writes back. An import fully replaces
  Condor's copy.
- **That repo's session** speaks for it. Its name changes over time (it
  has been `portfolio`, `investments-b9` and `invest-head`). Find it with
  `ListAgents`. It sends a message when an export is ready, says what
  Condor should show, and asks to be told about any disagreement.
- **Condor's handoff session** (on `main`) owns the app. It imports,
  checks Condor against what the record expects, reports back, and
  turns gaps into app work (`BACKLOG.md`, worktree branches). It does
  not track or decide portfolio matters. A question about how the owner
  invests goes back to that session, and only its app consequence lands
  in the backlog.

## Privacy rules

- Real data lives only in the **local** SQLite (`web/db.sqlite3` in the
  main checkout, gitignored). It never goes to the hosted (Fly) instance.
- **Nothing real goes into anything committed.** That covers code,
  comments, tests, fixtures, commit messages, briefs, ADRs and the
  backlog. No amounts, quantities, fills, cash figures, or real-ticker
  examples tied to the owner's positions. Describe a finding generically:
  "a reading of 19.995% against a threshold of more than 20%", "two
  cents after three half-cent fills".
- A branch brief describes the real case only in those terms. If real
  details reach a branch's commits anyway, rewrite the branch before
  merging, for example with
  `git filter-branch --tree-filter '<scrub script>' main..HEAD`. Once a
  commit is pushed, only a force-push removes it.
- Scratch copies of the real database (for a browser check) go in the
  session scratchpad and are deleted afterwards.
- No account numbers or other identifiers anywhere. A plain account label
  (for example `brokerage`) is fine.

## A new export comes in

The files are in `~/projects/investments/portfolio/exports/condor/`:
`ledger.csv`, `targets.csv`, `payin.csv` and `rules.csv`.

```bash
source .venv/bin/activate
E=~/projects/investments/portfolio/exports/condor
cp web/db.sqlite3 <scratchpad>/db.sqlite3.pre-import-<date>      # backup
python web/manage.py import_ledger $E/ledger.csv --targets $E/targets.csv \
  --payin $E/payin.csv --rules $E/rules.csv --user <owner> --replace --dry-run
python web/manage.py import_ledger $E/ledger.csv --targets $E/targets.csv \
  --payin $E/payin.csv --rules $E/rules.csv --user <owner> --replace
```

The dry run prints event count, cash, open tickers, tranches and rules.
Compare those with what the message said before running the real import.

## Check it against what the record expects

Read the account through the API rather than eyeballing the page. Use
Django's test client with `force_login`: no password is needed, and
nothing is printed but the numbers. The endpoints are `/api/account`,
`/api/account/tranche?apply_rules=1` (and `=0`), and
`POST /api/account/reconcile` with the broker's figures. Check:

1. **Holdings and counts** equal the export.
2. **Cash.** The broker check books each event half-up to the cent and
   is the number to compare with the broker. The headline uses exact
   fills and can be a cent or two off. That gap is a known backlog item,
   so don't chase it.
3. **Broker check.** Securities and value are at the last *final* close.
   Ask which close date the broker figures are, and compare like with
   like.
4. **Pay-in.** Compare `k_due`, `through` (with and without rules),
   `bought_through`, each list row (qty, due, the "carries forward"
   notes), the reservoir sale, and `carry` with the record's own tranche
   tool. A rule fires only on strictly more than its threshold.
5. **Rules.** `measured`, `fired`, `target_through` and `followed`.
6. **Report back** to the portfolio session: what matches, what doesn't,
   and any Condor change made because of it.

**Market hours.** The price store keeps a day's bar only once it is
final: after 17:00 New York time (ADR 0001 amendment). During the
session, Condor's "as of" is the previous close. That is intended.

## Looking at it in a browser

Never log in as the owner. Instead:

1. Copy the database to the scratchpad.
2. Run `migrate` against the copy with `CONDOR_DB_PATH=<copy>`.
3. Create a test user with a generated password, kept in a scratchpad
   file, and import the export for that user.
4. Run `CONDOR_DB_PATH=<copy> python web/manage.py runserver <port> --noreload`
   and sign in as the test user.
5. Delete the copy and the password file when done.

Chrome's window won't go below about 454 px wide. True phone width
(390 px) needs devtools device emulation or a phone.

## What real use has found that tests didn't

Every one of these passed the test suite until real use exposed it:

- **Prices froze after the first download** (2026-10-27). A minimum-rows
  check blocked every incremental update.
- **Time-weighted return dropped the first day's gain** (2026-11-01).
- **The broker check's rounding note was lost** to float noise just
  under a half cent (2026-11-01).
- **A reading that rounded to its threshold** printed beside "Not fired"
  (2026-11-22). It now says "just under / just over".
- **Live mid-session prices were stored as the day's close** (2026-11-23).
  This un-fired a rule, and could have stuck for good. The store now
  keeps final bars only and re-checks within the hour once a close is due.
- **A followed rule still looked like a to-do** (2026-11-23). The page
  now shows "bought through N", "Fired · followed" and "Left to buy
  through tranche K".
- **The reservoir was offered back** right after being sold to fund a
  tranche (2026-11-23). It is now bought only on day 1, and leftover
  cash carries.

Open items found the same way are in `BACKLOG.md` under the real-use
entry in **Now**.
