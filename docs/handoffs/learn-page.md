# Handoff — `feature/learn-page`

<!-- Copy of docs/handoffs/_template.md, seeded by scripts/new-worktree.sh.
     Lives at docs/handoffs/learn-page.md on the branch. Keep "Status" current. -->

| | |
|---|---|
| Branch | `feature/learn-page` |
| Worktree dir | `/Users/rtasseff/projects/condor-dev/learn-page` |
| Base | `main` @ `cb3d89c` |
| Created | 2026-09-05 |
| Runserver port | 8001 |
| Handoff session | `main` checkout at `~/projects/condor_v2/` |

Read this first, then `CLAUDE.md`, then `ARCHITECTURE.md`. This directory
is a git worktree: it *is* this branch — do not `git checkout` another
branch here (see `docs/WORKTREES.md`). Never run `fly` commands from this
directory; deploys happen from `main` after merge.

## Goal

Turn the nav's "Learn — coming soon" chip into a real, **public**
`/learn` page built around the Condor Funds YouTube channel
(youtube.com/@Condor_Funds) and a plain-words glossary of the app's own
vocabulary. RT decided (2026-09-05): public access (no login — the
videos are public and education is the front door; everything else
stays behind login) and first-version scope of **sessions + glossary +
"why Condor exists"** (no Shorts strip this round). This also delivers
the BACKLOG "Learn integration" item's first half: existing in-app
glosses gain "Learn →" links into glossary anchors.

The channel today: one teaching session — **"what is a portfolio?"**
(3:25, id `dyjYgHEM1og`) — and one founder interview — **"The Founder
of Condor Funds on how the project came to be."** (30:16, id
`jT6muQRTAeI`). More sessions are planned (indices, ETFs, S&P 500), so
the page's Sessions area must be a list that grows, not a one-off
layout. All summaries, glossary entries, transcript, and pull-quotes
you need are **in this brief** — do not invent content, and do not
fetch anything from YouTube at build time.

## Scope

**In:**

1. **Route + nav.** `GET /learn` (name `learn`), template
   `learn.html`, NO login required — this is the only public content
   page; do not touch auth anywhere else. Replace base.html's
   `<span class="soon">Learn</span>` with a real nav link (active
   state via a `nav_learn` block like the others). The Learn page
   belongs to neither world: no worldchip, neutral styling from the
   existing tokens. Login page gets one quiet line under the form:
   "New to investing? Start with Learn →". CHECK anonymous rendering
   end-to-end: base.html and every context processor must survive
   `AnonymousUser` (e.g. whatever computes `contribution_due` — guard
   it, don't crash). Nav links to Explore/My portfolio still render
   for anonymous visitors and simply redirect to login when clicked —
   that's fine.

2. **Sessions section.** A "Sessions" list (that vocabulary — it's
   what the videos themselves use). One entry today:
   "What is a portfolio?" (3:25). Card = title, one-line hook, the
   embed, "covers" term-chips linking to glossary anchors
   (#portfolio, #weight, #diversification, #index, #bond), and the
   full transcript in a labeled `<details>` ("Prefer reading? Full
   transcript"). Under it, a quiet pointer: "More sessions are on the
   way — subscribe on YouTube" linking the channel.
   - **Embeds are click-to-load facades** (privacy + weight): a
     thumbnail `<img>` from `https://i.ytimg.com/vi/<id>/hqdefault.jpg`
     with a play overlay; on click, swap in
     `<iframe src="https://www.youtube-nocookie.com/embed/<id>?autoplay=1">`
     (allowfullscreen, title set). No YouTube script/iframe loads
     before the click. Small caption: "Plays from YouTube". Keyboard
     operable (it's a real `<button>`).
   - After the swap the page talks to YouTube — that's expected and
     fine on our own site (no CSP here; `X_FRAME_OPTIONS` governs who
     frames *us*, not whom we embed).

3. **Glossary — "Plain words".** The 13 entries in Appendix A,
   verbatim (tone-polish only if something reads stiffly aloud). Each
   entry: `id` anchor, term, 1–3 sentence definition, optional
   "In the app:" line linking where it lives. Layout: simple stacked
   entries with generous whitespace, `:target` highlight so arriving
   via a "Learn →" link visibly lands on the term. Anchor-linkable
   (`/learn#dispersion` etc. — ids exactly as given, they are API now).

4. **"Why Condor exists" card.** Modest, after the glossary: the
   founder interview embed (same facade pattern) + the two pull-quotes
   in Appendix B + one line: "A 30-minute conversation with the
   founder about why this project exists." No transcript for this one.

5. **Contextual "Learn →" links in the app.** Add small links from
   existing glosses/controls to glossary anchors — at minimum:
   - Optimize's "Robust statistics (outlier-resistant)" gloss →
     `/learn#robust`
   - the Advanced priors disclosure ("What to assume about returns")
     → `/learn#anchor`
   - the forecast card/bands area → `/learn#bands`
   - Build's empty state gains: "New here? Watch the 3-minute session
     on portfolios →" (links `/learn`, opens same tab)
   - the frontier chart card → `/learn#frontier`
   Style: one shared `.learnlink` class, quiet, never competing with
   a primary action (explore-first's one-primary-action rule still
   holds).

**Out** (do not do here — belongs on `main` or another bucket):

- No Shorts strip, no comments, no analytics, no video hosting of our
  own, no engine/model/migration changes, no auth changes beyond the
  single public route, no route renames.
- Do not commit anything from `drive_export/` (the video content plan
  lives there; it stays out of git — this brief already carries what
  you need).

## Acceptance

- `curl` of `/learn` unauthenticated → 200 with sessions, glossary,
  and why-card present; `/` and `/optimize` and `/account` still
  redirect anonymous users to login (regression-test this).
- No iframe/YouTube request in the initial `/learn` HTML — facade
  only (test: response contains no `youtube-nocookie.com` iframe;
  clicking loads it, verified in-browser).
- All 13 glossary ids present exactly as specced; `/learn#robust`
  lands highlighted.
- Every in-app "Learn →" link resolves to an existing anchor
  (test iterates the pairs).
- Nav: Learn link active on `/learn`, "coming soon" chip gone.
- Both themes legible; facade images have alt text; details/summary
  keyboard-operable.
- Suites: core pytest and Django explorer tests not below baseline
  (record counts before/after; explore-first's baseline was 217+4
  core, 78 Django); `check` clean; **no new migration**
  (`makemigrations --check --dry-run` clean).

## Context & decisions already made

- RT (2026-09-05): public /learn; sessions+glossary+why scope; the
  channel is the content source; "learn button" = the existing nav
  chip. Don't re-open these.
- Vocabulary discipline (CLAUDE.md): *expected return*, *dispersion*,
  *robust*. The glossary is where those words get their public
  definitions — keep app copy and glossary wording consistent.
- The Sessions list will grow (planned: stock indices, S&P 500, ETFs,
  passive vs active). Structure sessions as data (a list in the
  template or a small Python constant), not bespoke HTML per video.
- Design: reuse tokens/cards from `style.css`; the page is calm,
  text-forward, no world tint. explore-first just shipped a stepper +
  two-world nav — Learn sits outside the journey, linked from within
  it.
- `docs/WORKTREES.md` § Review policy applies; this brief does NOT
  order a `/code-review` (front-end + one public read-only route =
  low risk). Your own Django tests + the acceptance list above are
  the layer. The handoff session will spot-check the auth boundary.

## Conflict watchlist

- None active. `base.html`, `login.html`, `optimize.html`,
  `home.html`, `style.css`, `views.py`, `urls.py`, `tests.py` are
  yours this round.

## Status

<!-- Branch agent keeps this current. Checklist + short dated notes. -->
- [x] Baseline suites recorded
- [x] /learn route + template, public, anonymous-safe base
- [x] Sessions card + facade embed + transcript disclosure
- [x] Glossary (13 entries, anchors, :target highlight)
- [x] Why-card (founder embed + quotes)
- [x] In-app Learn → links (5 sites) + login-page line
- [x] Tests (public 200, auth regression, anchors, no-iframe-in-HTML)
- [x] Suites re-run; counts vs baseline recorded here

**2026-09-05 — done, committed locally, not pushed.**

### Test counts

| Suite | Baseline | After |
|---|---|---|
| `pytest tests/` | 217 passed, 4 skipped | 217 passed, 4 skipped |
| `manage.py test explorer` | 78 OK | 93 OK (15 new, all in `LearnPageTests`) |
| `check` | clean | clean |
| `makemigrations --check --dry-run` | no changes | no changes |

### What landed where

- `web/explorer/learn.py` — new. All copy as constants: `SESSIONS`
  (a list, so the next video is an appended dict), `GLOSSARY` (13
  entries, ids in the specced order), `WHY`, and `learn_context()`
  which resolves in-sentence links at render time.
- `web/explorer/views.py` — `learn(request)`, the one view with no
  `@login_required`; nothing else in the auth setup was touched.
- `urls.py` — `path("learn", views.learn, name="learn")`.
- Templates — `learn.html`, `_facade.html` (the click-to-load embed,
  used twice); `base.html` nav chip → link; `login.html` line.
- `static/explorer/learn.js` — builds the player on click.
- `style.css` — one appended `Learn` section, tokens only, no new
  colors.

### Deviations / decisions worth a look

1. **`learn.js` sets `referrerPolicy="strict-origin-when-cross-origin"`
   on the iframe.** Found in the browser, not in review: the site
   answers with `Referrer-Policy: same-origin` (Django's default), the
   player gets no referrer, and YouTube refuses to start — *"Video
   player configuration error, Error 153"*. Relaxing it on that one
   element hands YouTube the origin and nothing else; the site-wide
   header is untouched. Verified before/after in Chrome: error card →
   the video plays. A test pins the string so it can't be tidied away.
2. **`base.html`'s plotly `<script>` is now inside
   `{% block headscripts %}`** so `/learn` can skip the chart library it
   has no use for. Default block content is the old tag verbatim —
   every other page renders byte-identically.
3. **The facade caption "Plays from YouTube" is a link** to the video's
   watch page. Same words as specced; it just means a visitor without
   JS still has a way to the video.
4. **Only the four "In the app:" lines the appendix actually gives**
   (portfolio, weight, whole-shares, anchor) shipped. I had drafted
   three more (robust, frontier, bands) and removed them — the brief
   says ship this text, don't invent content. Say the word and they're
   a five-line addition.
5. **Facade capped at 620px wide** — full column width made the page
   read like a video site rather than a page of prose.
6. **"Both themes legible"**: the app is dark-only today
   (`color-scheme: dark`, no light rules anywhere in `style.css`). The
   Learn CSS adds no color of its own — only existing tokens — so it
   follows whatever a future light theme does.
7. **Transcript shipped verbatim from Appendix A** — RT's proofread is
   still outstanding, as the brief anticipated. It lives in one place
   (`SESSIONS[0]["transcript"]`, a list of five paragraphs).
8. **Keyboard**: the facade is a real `<button>` with the handler bound
   to it, and the transcript is a native `<details>`, so both activate
   from the keyboard by construction. Synthetic keystrokes never
   reached the automation tab (an unfocused-window artifact — the page
   saw no `keydown` at all), so that leg was verified by construction
   and a mouse click, not by a keystroke landing.

### User-facing strings (before → after)

| Where | Before | After |
|---|---|---|
| `base.html` nav | `Learn` (dimmed "Coming soon" chip, not clickable) | `Learn` (link to `/learn`, active state on the page) |
| `login.html` | *(nothing under the form)* | "New to investing? **Start with Learn →**" |
| Optimize · Settings gloss | "…change one and re-run." | "…change one and re-run. **What robust means — Learn →**" |
| Optimize · Risk & Reward | "…The key above the chart names each marker." | "…names each marker. **The frontier, in plain words — Learn →**" |
| Optimize · Forecast | "…an honest range, not a promise." | "…not a promise. **Why the bands are wide — Learn →**" |
| Optimize · Advanced priors | "…It applies to both models." | "…both models. **Return to normal, explained — Learn →**" |
| Explore · empty draft | "Nothing yet — search above, or try a starter below." | same, plus "**New here? Watch the 3-minute session on portfolios →**" |

Nothing was renamed or removed; every change is an addition except the
nav chip becoming a link.

### Verified in the browser (localhost:8001)

`/learn` anonymous 200; thumbnail facade with no player in the HTML;
click → `youtube-nocookie` iframe, video plays; `/learn#robust` lands
on a highlighted entry; transcript disclosure opens; why-card shows the
founder embed and both pull-quotes; login page shows the new line.
`/`, `/optimize`, `/account` still bounce anonymous visitors to
`/login` (also regression-tested).

### Noticed, not fixed

- Nothing outside this bucket. The Error 153 referrer interaction
  (deviation 1) is the only pre-existing config wrinkle this work ran
  into, and it is fixed at the element rather than by touching the
  site-wide header.

## Questions for the handoff session

<!-- Anything needing the human or main. Don't guess — park it here and continue with what doesn't depend on it. -->
- RT's transcript proofread is still open (Appendix A shipped as-is).
- Want the three extra "In the app:" glossary lines I removed
  (robust → Settings, frontier → the chart, bands → the forecast card)?
  Deviation 4 above.

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
cd /Users/rtasseff/projects/condor-dev/learn-page
source .venv/bin/activate
python web/manage.py runserver 8001
```

`web/db.sqlite3` (accounts/logins) and `.condor_cache/` (price store) were
copied from the `main` checkout at creation time; both are per-worktree
and gitignored. The price store self-heals by re-downloading if stale.

---

## Appendix A — Glossary content (ship this text; ids are API)

Tone: plain words, second person, honest about uncertainty. "In the
app:" lines become links to the named page.

- **`portfolio` — Portfolio.** A group of assets you own, plus a
  decision about how much of your money sits in each one. That's it —
  a list and the amounts. *In the app: your mix on Explore is a
  portfolio the moment it has one asset.*
- **`weight` — Weight.** One asset's share of your total money. All
  the weights together add up to 100%. *In the app: the pie on
  Explore, and the sliders on Optimize.*
- **`diversification` — Diversification.** Spreading your money over
  many assets that don't all fail together. It keeps returns
  reasonable while lowering the damage any single asset can do — the
  video's house with many supports instead of one or two.
- **`expected-return` — Expected return.** Our estimate, from an
  asset's own history, of how it typically grows in a year. An
  estimate is a best guess, never a promise.
- **`dispersion` — Dispersion.** How widely returns swing around
  their middle — our word for risk. Two mixes can have the same
  expected return while one is a much wilder ride.
- **`robust` — Robust statistics.** Medians and other
  outlier-resistant measures instead of plain averages, so a few wild
  days in history don't dominate the picture. It's about *how we
  measure history* — not a prediction that the economy will be
  robust.
- **`frontier` — Efficient frontier.** For every level of dispersion
  there's a best-possible expected return; drawn together they form
  the curve on Optimize. Mixes below the curve leave return on the
  table for the risk taken.
- **`cal` — Cash and the straight line.** Mix the best risky
  portfolio with cash and your options trace a straight line on the
  chart — more cash slides you toward safety, less slides you up the
  line. The touching point is the best all-risky mix.
- **`index` — Index (like the S&P 500).** A stock portfolio built by
  a public rule rather than a manager's picks. The S&P 500 tracks
  roughly 500 large US companies; buying an index fund is buying that
  whole list in one purchase.
- **`bond` — Bonds and T-bills.** Lending money — to the US
  government, in a T-bill's case — for a modest, steady payback. The
  video's fortress: very safe, and a bit boring on its own.
- **`whole-shares` — Whole shares.** Real accounts buy whole shares,
  so your target mix gets rounded to what's actually buyable. *In the
  app: the trade report on My portfolio shows exactly what to buy or
  sell to get as close as possible.*
- **`bands` — Forecast bands.** We simulate many possible futures for
  your mix; the bands show where most of them land. They're wide on
  purpose — a narrow promise would be a lie.
- **`anchor` — "Return to normal".** An Advanced forecast setting:
  instead of trusting your mix's own history alone, blend it toward a
  long-run market assumption (about 8% a year) or a number you choose.
  *In the app: "What to assume about returns" on the forecast card.*

## Appendix B — Video copy (ship this text)

**Session: "What is a portfolio?"** (3:25, `dyjYgHEM1og`)
Hook line: "A house by the sea, held up by supports — the whole idea
of a portfolio in three minutes."
Covers-chips: portfolio, weight, diversification, index, bond.

**Why-card: founder interview** (30:16, `jT6muQRTAeI`)
Line: "A 30-minute conversation with the founder about why this
project exists."
Pull-quotes (verbatim from the video, lightly punctuated):
> "They want to make it sound complicated, because their jobs depend
> on the fact that they know it and you don't."
> "We meet them where they're at, we show them with actual data — and
> if they want to dig in more technically, they can."

**Transcript for the session** (from the video's own captions, lightly
punctuated for reading; RT proofreads before ship — it renders inside
the details disclosure):

So you want to invest in your future. Lots of possibilities out
there — we suggest a financial portfolio. Now what is that? Directly
put, it is a group of financial assets that one owns. Having a
diversified portfolio means you are investing in many different
financial assets: it helps maintain reasonable returns on investments,
but lowers the risk — if some go bad, you have others. A portfolio is
a set of assets and an amount, or percentage, otherwise called a
weight, on each of these assets.

Let's say you buy a small house over the ocean. There is probably a
bit of erosion, so you get the experts over, and they say you can get
two supports to help hold up the house. This gives you extra money to
buy great furniture, a big TV, electronics and a lot of fun stuff. The
experts don't give you any guarantee on what might happen in the
future — just their best guess. Now, one bad storm and everything
falls apart; you could lose everything. You can invest in a fortress
instead, that will never break — but now you invest all this money and
your house is going to be empty and rather boring. Now there is
something in between: you could get many different supports. You may
not have as many cool things in the house, but you can have some, and
it is fairly safe. One support breaks? Then you have time to either
replace it or repair it.

Let's continue this from a more specific financial view. Think of the
fortress as a bond — specifically a US treasury bill. It is basically
risk-free, but you invest, say, $10,000 and after 20 years you
probably get two or three thousand dollars back in profit. A boring
prospect within a boring room. Now let's say you're a bit more
adventurous, so you go into stocks — maybe one or two supports. Maybe
experts tell you what to expect; maybe you even have good data.
Whatever it is, guessing one or two stock prices is high risk —
there's definitely more to learn on this, but that's for another
session. Bottom line: the stock is probably 50/50 up or down. It could
even go bankrupt, and then you get nothing — your house crashing into
the water.

But you can invest in many stocks at once — a stock portfolio —
basically betting on the whole US economy, not one company. Of course
there are ups and downs even across the whole economy, but long term
the US economy has always gone up. As an educational example, the
S&P 500 is an index — a type of stock portfolio made up of about 500
companies; more information on that in another session. The bottom
line is, it shows that over the last 100 years the market goes up and
down, but on average, in the long term, it goes up — and over 10 or 20
years it goes up a lot more than one single bond. And through every
financial crisis we have, it still goes up, given enough time.

Even though it may not feel like it, the US economy has a chance for
an everybody-wins scenario — because the US economy constantly grows.
The only real problem is getting all good working people the right
tools and opportunities to take part in that growth. Now, your
portfolio can include lots of opportunities for diversification: many
combinations of US stocks, international stocks, bonds, commodities.
There are several other sessions and external sources we can point you
to for more information — on assets, stock indices, diversification,
and the possible downside of current services, including large
investment banks and hedge funds.
