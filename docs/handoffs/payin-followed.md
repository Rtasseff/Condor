# Handoff — `feature/payin-followed`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/payin-followed.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/payin-followed` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/payin-followed` |
| Base | `main` @ `46fd9d9` |
| Created | 2026-11-23 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Make the pay-in panel say when the investor is done, using a real case from 2026-11-23. A fired
index-drawdown rule ("buy 2 tranches early") was followed. Condor still showed the rule as
**Fired**, titled the list **"Buy list for tranche K"**, and added **"Put the rest in RES: buy
N"**, right after the investor had sold reservoir shares to fund the buys. Nothing on the page
said the rule had been acted on. The portfolio repo (the
record) agreed the three display changes below and asked that the reservoir buy-back go.

Nothing about the owner's real plan goes in code, copy or committed fixtures. Use made-up
tickers and amounts, as `tests/test_payin.py` and `web/explorer/test_account_plans.py` already do.

**Read first:** `docs/decisions/0007-payin-rules-xirr.md`, `condor/payin.py`, `condor/alerts.py`
(`accelerations`), `web/explorer/account.py` (`_payin_numbers`, `_payin_payload`, `_rule_dict`,
`_rule_results`, `api_account_tranche`), `web/explorer/static/explorer/account.js`
(`renderPayin`, `renderTranche`, `renderRules`), `docs/research/ui-conventions.md`.

## Scope

**In:**
1. **Bought through tranche N.** Show, from holdings, how far the pay-in has actually been
   bought. It survives an acceleration, unlike `k_due`.
2. **"Fired · followed"** for a fired `accelerate` rule whose acceleration the holdings
   already cover.
3. **"Left to buy through tranche K"** as the buy-list title.
4. **No reservoir buy-back after day 1.** Leftover cash is held until the next tranche, which
   is what the investor's own tool does. Show it as a note instead.
5. An ADR 0007 amendment recording all four.

**Out:**
- Anything about what happens at the **next** tranche date while a rule stays fired. That is
  pending decision O7, which belongs to the owner (see below). The copy must stay neutral: no
  "next month this becomes tranche 5" text.
- Booked-to-the-cent cash in the headline (a separate backlog item).
- Manual (non-mirror) account pay-in UI.

## Context & decisions already made

**Bought through (engine, `condor/payin.py`):**
`bought_through(plan, bought, prices, tickers=None) -> int` is the largest k in 0..N for which
the dca buy list through k buys nothing for `tickers`. `tickers` defaults to every dca ticker;
non-dca tickers passed in are ignored.
- For each ticker, take `due_k = max(total·w·k/N − bought, 0)`. The test is
  `round_qty(due_k, price) == 0`, the same half-up whole-share rule `tranche_orders` uses, so
  "bought through" and the list can never disagree.
- Budget is ignored (this measures holdings, not cash). Lump and reservoir are excluded.
- A missing price raises `KeyError`, as `tranche_orders` does.
- Due is non-decreasing in k, so a scan is fine. N is small.
- Hand-case test: 0.49 of a share still due counts as bought, 0.51 does not. Also test k = 0
  (nothing bought) and k = N.

**Rule target and followed (engine, `condor/alerts.py`, beside `accelerations`):**
`rule_target(result, k_due, n) -> int | None` is the tranche a fired `accelerate` rule asks
the account to be bought through. Return None for rules that are not fired, not
`accelerate`, or have no `tranches`.
- Untargeted: `min(k_due + tranches, n)`.
- Targeted: `min(max(k_due, 1) + tranches, n)`.
- Test that it equals what `accelerations` produces for that rule alone: `through` for
  untargeted; `min(through + extra[t], n)` for targeted.

`followed` is true when `bought_through(plan, bought, prices, tickers)` is at least the rule's
target. `tickers` is the rule's targets when the rule is targeted, all dca tickers otherwise.
- Example: 0.51 of a share short in one targeted ticker means **not** followed, and that share
  is exactly what the list shows. The investor and Condor then see the same thing.

**Reservoir (engine, `condor/payin.py` `reservoir_trade`):**
- When buys exceed cash, keep the SELL exactly as now (ceil, capped at held, `short`).
- When cash covers the buys, BUY only while the reservoir has **never been bought**, i.e.
  `bought.get(reservoir, 0) == 0`. That is day 1, when the reservoir gets funded; test
  `test_day_one…` relies on it. Otherwise return None.
- Add the parameter you need (for example `funded: bool`). Don't infer it from `held`: a
  reservoir sold down to zero later is still funded.
- Add `leftover_cash(cash, buy_total, trade) -> float`: the cash left after the list and the
  reservoir trade, never below 0 (`short` means 0).

**API (`web/explorer/account.py`), add keys, rename nothing:**
- Pay-in payload: add `bought_through`. Use None if a price is missing; never fail the page.
- Each rule dict: add `target_through` (int or None) and `followed` (bool, or None when not
  applicable: not fired, alert rules, muted, no plan, or a missing price).
- `/api/account/tranche`: `reservoir_trade` follows the new engine rule. Add `carry`: the
  leftover cash from `leftover_cash`, rounded to the cent.

**UI (`account.js` and `account.html`). Quote every string before → after in Status:**
- Pay-in title: `Pay-in: tranche 2 of 6 · next 2026-12-21` becomes
  `Pay-in: tranche 2 of 6 · bought through 3 · next 2026-12-21`.
  - Show the "bought through" part only when it is a number.
  - When the pay-in is complete, keep the current title.
- Rules table status: fired with `followed === true` reads `Fired · followed`. Every other
  status is unchanged ("Fired", "Not fired", "Muted during pay-in").
- Buy-list title: `Buy list for tranche K` becomes `Left to buy through tranche K`.
  The empty row: `Nothing to buy through this tranche.` becomes
  `Nothing left to buy through tranche K.`
- The `Put the rest in RES: buy N (~$X)` sentence stays for the day-1 funding case only,
  because the engine now returns a BUY only then.
- When `carry` ≥ 0.01, add `~$X cash carries to the next tranche.` If the pay-in has no next
  date, say `~$X stays in cash.` instead. This sits in the same line as the sell sentence.
- Neutral about the future: no text that predicts the next date's list.

**Pending decision O7: the owner's, not ours. Do not resolve it.** It concerns an untargeted
rule that stays fired.
- Reading A (current, keep it): "stay two ahead while fired", `through = k_due + tranches`,
  re-evaluated every day.
- Reading B: "once per fall". A firing buys the next two unbought tranches once and re-arms
  when the index closes back within the threshold.
- The ADR amendment records both readings and says A stands until the owner answers. Nothing
  you build may assume B.

## Acceptance

- The four baseline commands are not worse. Explorer and core suites have new tests:
  - engine hand cases for `bought_through`, `rule_target` (equals `accelerations`),
    `reservoir_trade` (day-1 BUY kept; no BUY once funded; SELL unchanged) and
    `leftover_cash`;
  - explorer tests for `bought_through`, `followed` (true, false at 0.51 of a share, None
    when not fired) and `carry`;
  - the existing `reservoir_trade` expectations updated where the BUY used to appear after
    day 1, with each change noted in Status.
- ADR 0007 has a dated amendment (2026-11-23) covering bought-through, followed, the
  reservoir rule, `carry`, and O7 pending with readings A and B.
- A browser pass on port 8001, with your own made-up mirror account (import a small ledger
  via `import_ledger --user <you>` into the worktree DB). Confirm:
  - title, rule status, list title, carry note;
  - phone width (≈390 px) does not overflow.
  
  Do not open or use the `rtasseff` account in this worktree's DB.
- **Review:** I run `/code-review medium` on this branch after you report done (main may move
  meanwhile), and I'll send any fixes back. Don't run it yourself.

## Conflict watchlist

- `web/explorer/static/explorer/account.js`: main just added `measuredText` in `renderRules`
  (b2dd2e0). Build on it.
- `condor/data/store.py` and `tests/conftest.py` changed on main (46fd9d9). The suite's store
  clock is pinned after today's close. Not your area.

## Status

- [ ] Baseline recorded
- [ ] Engine: bought_through, rule_target, reservoir rule, leftover_cash + tests
- [ ] API keys + explorer tests
- [ ] UI strings (before → after listed here)
- [ ] ADR 0007 amendment
- [ ] Browser pass (desktop + phone width)

## Questions for the handoff session

-

## Return protocol

1. Keep this doc's **Status** current; note anything you deviated from.
2. Record your baseline **before starting**, then re-run before pushing —
   do not make any count worse:
   ```bash
   source .venv/bin/activate
   python -m pytest tests/
   python web/manage.py test explorer
   python web/manage.py check
   python web/manage.py makemigrations --check --dry-run
   ```
   Engine changes need a verification-style test (closed form / hand case /
   legacy agreement); model changes need an "equals the engine" test
   (CLAUDE.md rules apply on branches too).
3. If this brief orders a `/code-review` (it will say so explicitly when
   the bucket touches engine numerics, auth/permissions, ledger
   migrations, or deploy config): run it at *medium* on this branch and
   land the fixes as your final commit, summarised in Status.
4. **Do not push, do not open a PR, do not merge.** Your report packet
   is THIS doc: Status checklist current, deviations listed, every
   renamed user-facing string quoted (before → after), test counts vs
   baseline, any pre-existing bug noticed but not fixed. Commit it all
   locally and tell the human you are done.
5. The handoff session reviews proportionately — spot-checks, never a
   redo (`docs/WORKTREES.md` § Review policy) — merges your local
   branch, pushes `main`, and the human deploys.

## Running locally (this worktree)

```bash
cd /Users/rtasseff/projects/condor-dev/payin-followed
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.
