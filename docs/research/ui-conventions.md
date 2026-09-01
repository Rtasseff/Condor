<!-- Research agent report, 2026-09-01: consumer finance-app UI conventions, audited against this repo's code. -->

# UI/UX conventions report — Condor Funds Portfolio Explorer

*Research brief + prioritized change list for BUILD (`/`) and MY ACCOUNT (`/account`).*

---

## 0. What this is based on

I read the live code before writing recommendations, so every item below names a real file and a real line. Note the working tree is **dirty** — four files are mid-edit and already contain part of the fix for the zoom complaint:

| Already done in your uncommitted diff | Where |
|---|---|
| `dragmode: false` on all four charts | `app.js:375, 628`; `account.js:101, 541` |
| `legend.itemclick/itemdoubleclick: false` on all four | same lines |
| `#chart .nsewdrag { cursor: pointer !important }` | `style.css:402` |
| Chart-area loading panel + spinner + reduced-motion guard | `index.html:66-71`, `style.css:404-410`, `app.js:153-156, 188` |

Those are all correct and match convention. The list below is what is *still* missing, plus the intuitiveness work.

Two constraints I kept to: **ADR 0003** (no npm, no bundler, no build step) rules out every tour library; **ARCHITECTURE.md** forbids numerics in JavaScript, so nothing here adds math to the front end.

---

## 1. DO NOW — high impact, low effort

### 1.1 Finish the zoom lockdown: the `config` object, not just `dragmode`

**Convention.** Consumer finance charts expose *no* free zoom. Apple Stocks gives preset range tabs plus touch-and-hold to read a value; Yahoo Finance puts 1D/5D/1M/6M/YTD/1Y/5Y/MAX buttons under the chart and reserves scroll-to-scale for the *full-screen advanced* chart. Zoom/pan is a pro-surface affordance (TradeStation, TradingView), not a retail one.

**Why yours can still zoom.** `dragmode: false` only kills drag on the **main** drag layer. Plotly's per-axis drag handles (`showAxisDragHandles`, default `true`) pan/zoom independently of `dragmode`, and `doubleClick` still defaults to `'reset+autosize'`. `showTips` also defaults to `true`, so Plotly may show your users a "double-click to zoom back out" hint for an interaction you deliberately removed.

**Change (one line each), in `app.js` and `account.js` — all four `Plotly.react` config objects:**

```js
{ displayModeBar: false, displaylogo: false, responsive: true,
  scrollZoom: false, doubleClick: false, showTips: false,
  showAxisDragHandles: false, showAxisRangeEntryBoxes: false }
```

**And in each `layout`, belt-and-braces:** add `fixedrange: true` to both `xaxis` and `yaxis`. When *both* axes are fixed, Plotly disables pointer events on every non-main dragger but deliberately keeps the main drag layer alive **for hover** — and `clickFn` is independent of `dragmode`, so your custom `pointerdown`/`click` handler in `wireChartClicks()` (`app.js:414-434`) is untouched.

**Do not** use `staticPlot: true`. It removes the `.drag` layers from the DOM entirely, killing hover tooltips *and* clicks. It is the trap that looks like the obvious answer.

*Sources: [Plotly config source](https://github.com/plotly/plotly.js/blob/master/src/plot_api/plot_config.js), [dragbox.js](https://github.com/plotly/plotly.js/blob/master/src/plots/cartesian/dragbox.js), [graph_interact.js](https://github.com/plotly/plotly.js/blob/master/src/plots/cartesian/graph_interact.js), [Plotly forum — maintainer recommends `dragmode: false`](https://community.plotly.com/t/disable-zoom-but-keep-click-enabled/10492), [Apple Stocks](https://support.apple.com/guide/iphone/check-stocks-iph1ac0b1bc/ios), [Yahoo Finance chart help](https://help.yahoo.com/kb/period-scale-screen-charts-yahoo-finance-web-sln28287.html)*

---

### 1.2 Fix the mobile touch story: let the page scroll

**Convention.** A chart must never trap the page scroll. Plotly issue [#2844](https://github.com/plotly/plotly.js/issues/2844) (still open) is exactly this: *"The chart's default behaviour is zooming. It makes page scrolling impossible, unless label area is used for that."*

**Change.** In `style.css`, next to your existing `.nsewdrag` rule:
```css
#chart, #fchart, #achart, #afchart { touch-action: pan-y; }
```
`dragmode: false` also skips Plotly's `e.preventDefault()` on `touchstart` (the handler is guarded by `options.dragmode !== false`), which removes the Chrome "[Intervention] Ignored attempt to cancel a touchstart event" warning class as a bonus.

---

### 1.3 Stop relying on hover to say "click me" — hover is broken on touch

**Convention + evidence.** Your `hovertemplate`s already carry `<i>click to inspect this mix</i>` (`app.js:250, 267, 296, 314`). Good instinct, wrong channel. Plotly's tap-to-hover regressed in v1.29 and has never been fixed ([#1967](https://github.com/plotly/plotly.js/issues/1967)) — there is no supported tap-to-show-tooltip. And on desktop, the affordance research is blunt: in *"Click or not: different mouseover effects may affect clicking-through rate"* (2019), **more than 60% of users failed to click hovered elements** even when highlighting and a hand cursor were present; 5 of 7 tested designs measurably improved click-through, but none came close to solving it. Cursor + hover text is necessary and *not sufficient*.

**Change.** Add a persistent, always-visible affordance inside the plot. One `layout.annotations` entry pinned to the paper, top-left of the plot area:
```js
annotations: [{ xref: "paper", yref: "paper", x: 0.01, y: 0.99,
  xanchor: "left", yanchor: "top", showarrow: false,
  text: "Click anywhere on the chart to inspect that mix ↓",
  font: { size: 12, color: C.muted } }]
```
Keep the hovertemplate text too. This is the single highest-value change for "doesn't seem intuitive."

---

### 1.4 Make the loading feedback match the 10-second rule

**Convention.** Nielsen's thresholds: 0.1 s instant, 1 s flow, **10 s = the limit of attention**. NN/g: *"use a looped indicator for delays of 2–9 seconds and a percent-done indicator for delays of 10 seconds or more"*, and include contextual text like *"Updating address 3 of 50"*. A 5–30 s action must be treated as the >10 s case, because the user cannot know in advance which they're getting. NN/g also cites research where users given moving feedback *were willing to wait roughly 3× longer*.

Your new spinner is a looped indicator — correct for 5 s, under-specified for 30 s.

**Change.** In `analyze()` (`app.js:144-189`), advance the `#chart-loading` text on a timer instead of leaving one frozen string: `"Fetching price history…"` → (~4 s) `"Downloading N series…"` → (~6 s) `"Computing statistics…"` → (~12 s) escalate to `"Still working — the first run for a new ticker downloads 10 years of history."` Clear the timer in `finally`.

**One caveat worth heeding.** Conrad, Couper, Tourangeau & Peytchev (*Interacting with Computers* 22(5), 2010, n=3,179) found progress framing swings abandonment nearly 2×: slow-to-fast framing produced **21.8%** breakoff vs **11.3%** for fast-to-slow, χ²(3)=31.57, p<.001. Front-load the steps that complete quickly; never sit on one message for 25 of 30 seconds.

*Sources: [NN/g Response Times](https://www.nngroup.com/articles/response-times-3-important-limits/), [NN/g Progress Indicators](https://www.nngroup.com/articles/progress-indicators/), [NN/g Designing for Long Waits](https://www.nngroup.com/articles/designing-for-waits-and-interruptions/), [Conrad et al. 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2910434/)*

---

### 1.5 Add the missing loading feedback on MY ACCOUNT

**Gap found in code.** Three server round-trips have **zero** feedback and no button disable:
- `loadPlan()` (`account.js:296`) — wired to `#planbtn`, hits `/api/account/plan` (needs last-close prices)
- `loadContribution()` (`account.js:399`) — wired to `#scplan` and `#duego`
- `init()` (`account.js:590`) — the whole page sits showing `–` in all four tiles with no indicator while `/api/account` values the ledger

NN/g's *Visibility of System Status*: users who click and get nothing "have been burned before by technology that didn't work properly" and re-click.

**Change.** Give `#planbtn` and `#scplan` the same treatment `#aforecast` already has (`account.js:478-479`): disable + a `role="status"` span reading `"Pricing…"`. For `init()`, show a one-line `"Valuing your account at the last close…"` in `#a-asof` until `render()` runs.

---

### 1.6 `hovermode: 'x unified'` on the three time-series charts

**Convention.** For a date/time x-axis with several series, one consolidated readout beats N stacked labels. Plotly default is `'closest'`, which on your fan chart means hovering gives you *one band edge* — meaningless. `'x unified'` also auto-enables spikelines perpendicular to x, which is the finance-chart crosshair convention (Apple Stocks, TradeStation, amCharts, Google Charts all use a crosshair on a time series).

**Change.**
- Frontier chart (`app.js:379`) — **leave as `'closest'`**. Each point is a separate clickable object, and multiple portfolios can share a risk value, which `'x unified'` cannot represent.
- `#fchart` (`app.js:618`), `#achart` (`account.js:81`), `#afchart` (`account.js:531`) — add `hovermode: "x unified", hoversort: "value descending"` and `xaxis: { …, spikethickness: 1, spikedash: "dot", spikecolor: C.axis }`.

Also add `hoverdistance: 30` to all four layouts (default is 20 px — tight for novices and for touch).

---

### 1.7 The BUILD empty state contradicts itself

**Bug.** `init()` calls `analyze()` on every page load (`app.js:916`), with seven tickers preloaded in `state.assets` (`app.js:26`). So `#chart-empty`'s copy — *"Add assets on the right, then hit **Analyze**."* (`index.html:65`) — describes a state that essentially never happens; and on any viewport under 900 px the sidebar is **below** the chart, not "on the right" (`style.css:196-197`).

**Change.** Rewrite to describe the real failure state: `"No results yet — add an asset below and press Analyze."` (drop the directional word entirely).

---

### 1.8 Label the preloaded portfolio as an example

**Convention.** Preloaded demo data is a well-established substitute for an empty state — Pipedrive ships a sample pipeline; Keyhole reported activation rising to 45% after replacing an empty dashboard with demo data. You already do the hard part (7 tickers, auto-analyze). What's missing is telling the user it isn't theirs.

**Change.** In `index.html:87`, change the sidebar heading to `Your portfolio <small class="sub">— starts as an example; swap these out</small>`.

---

### 1.9 Tell the cold lander what the app is, on the login page

**Gap.** `login.html` says only *"Accounts are created by the team admin."* A user's first screen never states what Condor does, so they arrive on a dense dashboard with no frame.

**Change.** Add one line under the `Sign in` heading: `"Build a portfolio, see its risk/reward tradeoff, and track a pretend account."`

---

### 1.10 Kill or fill the dead nav

**Gap.** `base.html:22-26` renders `Learn`, `Compete`, `Develop` as bare `<span>`s. There is no `learn` route in `urls.py`. Three of the five nav items do nothing — for a cold user this reads as a broken app, and it's the first thing on the page.

**Change.** Wrap them in `<span class="soon" title="Coming soon">` with a dimmed style, or drop them until they exist. (`Learn` is the natural home for §2.3's glossary — see DO SOON.)

---

### 1.11 Scroll the point card into view on selection

**Gap.** `#chart` is a fixed 520 px (`style.css:201`) and `#pointcard` sits below it. On a laptop, clicking the chart puts the result below the fold — the user sees the teal ring appear and nothing else, which reads as "nothing happened." Your own `#duego` handler already does this correctly (`account.js:582`).

**Change.** In `selectPoint()` (`app.js:443-448`), after `renderPoint()`: `$("pointcard").scrollIntoView({ behavior: "smooth", block: "nearest" })`.

---

### 1.12 Accessible-name the charts

**Convention.** Plotly's SVG output has no ARIA roles and no accessible name — open issue [#6920](https://github.com/plotly/plotly.js/issues/6920) since March 2024. The standard workaround is `role="img"` plus `aria-labelledby`/`aria-describedby` on the container.

**Change.** `#chart` already has `aria-label` (`index.html:64`) — good; add the same to `#fchart`, `#achart`, `#afchart`, and add `role="img"` to all four. Also add `aria-busy="true"` to `#chart` during `analyze()` and clear it in the `finally` block (guard it in `finally` — a leaked `aria-busy="true"` silences all future updates to that subtree).

---

## 2. DO SOON — real value, more than an hour

### 2.1 Range buttons on the account "Value over time" chart

**Convention.** This is *the* consumer finance chart convention and you're the only one not doing it: Yahoo Finance (1D/5D/1M/6M/YTD/1Y/5Y/MAX under the chart), Apple Stocks (range tabs at the top — *"preset time period options rather than requiring zooming gestures"*), Google Finance. Preset ranges are how consumers get "zoom" without a zoom gesture.

**Change.** `#achart` has a date x-axis (`account.js:81-84`) and no range control. Add `xaxis: { type: "date", rangeselector: { buttons: [{count:1,label:"1m",step:"month",stepmode:"backward"}, {count:6,label:"6m",step:"month",stepmode:"backward"}, {label:"YTD",count:1,step:"year",stepmode:"todate"}, {count:1,label:"1y",step:"year",stepmode:"backward"}, {step:"all",label:"All"}] } }` — and style the buttons with the dark tokens (`bgcolor: C.surface2, activecolor: C.accent, font: {color: C.ink2}`), or they render in Plotly's light default and look broken on your theme. **Do not** add `rangeslider` — that's a zoom control by another name.

### 2.2 Jargon: layered, not hidden

**Convention.** Real products layer explanations rather than choosing one channel. Morningstar: *"you can find definitions across the site for key terminology; click the 'i' icon to learn more."* Schwab ships a 100+ term glossary and a deliberately layered UI where *"basic research is front and center and advanced features are accessible but not forced."*

**The constraint that matters.** NN/g's info-tips guidance is explicit: **"Assume that most users will never see the info tip."** So an "i" icon is for *supplemental* content only — anything the user needs in order to make a decision must be visible inline. And NN/g on tooltips: they're hover-triggered and *"can be used only on devices with a mouse or keyboard"* — on touch you need a click-triggered popup, not a tooltip. Separately, your four `title=` attributes (`index.html:39, 79, 94, 96`) are the weakest option available: no touch, no keyboard, delayed, unstyleable.

**Change, three tiers:**
1. **Rename in place (free, biggest win).** Your stat tiles (`index.html:106-108`) already do half of this with `<small>(annual σ)</small>`. Add a plain-language second line under each `.tile .value`: Expected return → *"what it averaged per year"*; Dispersion → *"how bumpy the ride was"*; Sharpe → *"reward per unit of bumpiness — higher is better"*. Keep the Condor vocabulary as the label (ARCHITECTURE.md requires *expected return* / *dispersion* / *robust*); the gloss sits underneath.
2. **Click-triggered "i" popups** for the second layer (efficient frontier, capital allocation line, tangent portfolio, TWR, drift, DCA). A `<details>`/`<summary>` disclosure is the zero-JS, keyboard-accessible, touch-safe version and needs no library.
3. **A `/learn` glossary page** as the third layer, which finally makes the dead `Learn` nav item real.

*Sources: [NN/g Why So Many Info Tips Are Bad](https://www.nngroup.com/articles/info-tips-bad/), [NN/g Tooltip Guidelines](https://www.nngroup.com/articles/tooltip-guidelines/), [NN/g on the title attribute](https://www.nngroup.com/articles/title-attribute/), [Morningstar glossary](https://www.morningstar.com/help-center/morningstars-approach-to-investing/glossary-of-investing-definitions), [Schwab glossary](https://eac.schwab.com/equity101/investing101/investing-resources/glossary)*

### 2.3 Thin the wall-of-text `.sub` paragraphs with progressive disclosure

**Convention.** Progressive disclosure (Nielsen, 1995): show the essentials first, reveal depth on demand. Your Forecast card's intro (`index.html:114-121`) is a 6-line paragraph *above* the control the user came to press; the account Forecast (`account.html:180-186`) and Ledger (`account.html:216-220`) are the same shape. The content is genuinely good — it's just front-loaded.

**Change.** Keep the first sentence visible; move the rest into `<details><summary>How this model works</summary>`. Zero JS, keyboard-accessible, and it survives ADR 0003.

### 2.4 Meaningful button loading states

**Convention.** NN/g on button states: show a spinner **to the left of the button label**, and prefer `aria-disabled="true"` over native `disabled` so the button keeps keyboard focus (native `disabled` blurs it, dumping focus to `<body>` — the user loses their anchor exactly when results appear). The actual double-submit guard should be an early `return` in the handler, not the attribute.

**Change.** In `analyze()` (`app.js:150-151`) and `runForecast()` (`app.js:546-548`): swap `btn.disabled = true` for `btn.setAttribute("aria-disabled","true")` + an `if (state.busy) return;` guard, and change the label to `"Analyzing…"` / `"Projecting…"` rather than leaving `#status` to carry it alone. Style `button[aria-disabled="true"] { opacity:.55; cursor:wait; }`.

### 2.5 A one-time, dismissible first-visit hint — *if* 1.3 isn't enough

**Convention + the honest caveat.** NN/g's verdict on tours is harsh: *"Tutorials interrupt users, don't necessarily improve task performance, and are quickly forgotten"*, and in their study users who **read** tutorials rated ease-of-use **lower** (4.92) than users who **skipped** them (5.49) — a tutorial can make an app feel harder than it is. Their recommendation is contextual, just-in-time help, and above all: *"avoid creating app onboarding whenever possible and instead spend resources making the UI more usable."*

So: do 1.3 (a permanent visible affordance) first, ship it, and only add a hint if a user still misses it. If you do, make it **one** dismissible chip anchored to the chart — not a multi-step tour — gated on `localStorage` (there is currently no localStorage use anywhere in `app.js`/`account.js`). Keep it under ~140 characters and make dismissal permanent.

*Sources: [NN/g Onboarding Tutorials vs. Contextual Help](https://www.nngroup.com/articles/onboarding-tutorials/), [NN/g Mobile Tutorials](https://www.nngroup.com/articles/mobile-tutorials/), [NN/g Instructional Overlays and Coach Marks](https://www.nngroup.com/articles/mobile-instructional-overlay/), [NN/g Onboarding: Skip it When Possible](https://www.nngroup.com/videos/onboarding-skip-it-when-possible/)*

### 2.6 A `<details>` data-table fallback under each chart

**Convention.** *"Having alternative tables to graphs is part of accessibility requirements for screen readers"*, and given Plotly's open accessibility gaps ([#6920](https://github.com/plotly/plotly.js/issues/6920), [#4264](https://github.com/plotly/plotly.js/issues/4264) — scatter/bar charts not keyboard-operable), it's the only reliable route. It doubles as the mobile fallback for the broken tap-to-hover.

**Change.** You already have `#assettable`. Add a `<details><summary>View as table</summary>` under `#fchart` and `#achart` with the same numbers.

### 2.7 Direct-label the three anchor markers — *with a caveat*

**Convention.** Direct labeling beats a legend: it *"reduces dependence on legends"* and removes the color-identification task, which matters for CVD. Your frontier legend currently carries 8 entries and your own copy tells users to do the zig-zag (*"The key above the chart names each marker"*, `index.html:62-63`).

**The caveat — read before doing this.** `app.js:229-230` records a deliberate decision: *"Identity lives in the key (legend) — no annotations chasing markers around the plane"*, and `docs/REVIEW.md` lists "key/legend instead of chasing labels" as a shipped fix from RT's review round 1. You tried labels and rejected them.

**Change, narrowly.** Don't relitigate that. Label only the **three fixed anchors** — Tangent, Min dispersion, Your portfolio — as static annotations with a small `ay` offset and `showarrow: true`. Those three don't move around the plane the way per-point labels did. Keep the legend for everything else. Treat as an experiment, easy to revert.

---

## 3. SKIP — common elsewhere, wrong for a 5-user education-first tool

| Skip | Why it doesn't fit |
|---|---|
| **Multi-step product tours** (Appcues/Userpilot/Pendo/Shepherd.js/intro.js) | ADR 0003 bans npm; NN/g finds tutorial-readers rate ease-of-use *lower* than skippers. Vendor blogs claiming "78% abandon tours" and "76.3% of tooltips dismissed in 3 seconds" are marketing for tour products — I'd not build a decision on them, but they don't argue *for* tours either. |
| **Skeleton screens for Analyze** | NN/g scopes skeletons to 2–10 s *page loads*, explicitly *"not for non-page-load processes (uploads, computations)."* Viget's n=136 test found skeletons perceived as the **slowest** of three conditions (2.82 s est. vs 2.41 s spinner vs 2.29 s blank; 59% vs 74% agreed it "loaded quickly"). Your in-place progress text is the better pattern. |
| **A percent-done progress bar** | You cannot compute a true percentage for a price download. Apple HIG and NN/g both warn that inaccurate progress destroys credibility; a bar stalled at 99% is worse than honest staged text. Use step counts instead (§1.4). |
| **Free zoom / pan / `rangeslider`** | The complaint that started this. Consumer surfaces don't have it; only pro surfaces (TradeStation, TradingView) do. A `rangeslider` is a zoom control wearing a costume. |
| **Interactive legend toggling** | Plotly's defaults are `itemclick: 'toggle'` and `itemdoubleclick: 'toggleothers'` — a novice double-tapping the legend to read it makes the entire chart vanish, with no visible undo. You already disabled it; keep it disabled. |
| **Modebar (even trimmed)** | Camera/lasso/autoscale icons are analyst furniture. For 5 novices, `displayModeBar: false` is correct. |
| **Native `title=` attributes as the help mechanism** | No touch, no keyboard, ~1 s delay, unstyleable, and screen-reader support is inconsistent. Replace the four in `index.html` with visible microcopy or `<details>`. |
| **A global loading overlay** | Convention (Primer, Carbon, NN/g) is to scope the indicator to the region that changed. Your chart-area panel is already right; don't escalate it. |
| **Optimistic UI on Analyze** | Requires sub-2 s, low-risk, binary actions. A 5–30 s network-dependent computation is the textbook counter-example. |
| **A dedicated onboarding/welcome modal** | Five trusted users you can talk to directly. NN/g: spend the effort making the UI self-evident instead (§1.3, §1.7, §1.8). |

---

## 4. Condensed findings by research area

**1 — Chart etiquette.** Consumer surfaces (Google Finance, Yahoo's default chart, Apple Stocks) give **preset range buttons + hover/scrub**, never free zoom; zoom lives on pro surfaces. Crosshairs on time series are near-universal. Legends are static keys, not filters. Touch convention is **tap or touch-and-hold to read a value** (Apple Stocks: *"touch and hold the chart with one finger to view the value for a specific date"*; TradeStation: tap selects, hold shows the crosshair) — never pinch-to-zoom on a consumer readout. Click affordance is weak everywhere: cursor + hover highlight still leaves >60% of users not clicking, so the affordance must be *written on the chart*.

**2 — First-run guidance.** The literature converges on *don't onboard, design better*. NN/g: tutorials interrupt, don't improve task performance, are quickly forgotten, and can lower perceived ease-of-use. What does work for a small app: an **empty state that teaches**, **preloaded sample data** so the product is already "working" on arrival (you do this — you just don't label it), **progressive disclosure** of depth, and **one** contextual just-in-time hint rather than a sequence.

**3 — Jargon.** The working pattern is layered, and the layers have different rules: plain-language gloss **always visible**; "i" icon for the *supplemental* layer only (NN/g: assume most users never open it); glossary page for the deep layer. On touch, use click-triggered popups, not hover tooltips. Morningstar and Schwab are the clearest exemplars. Formatting hygiene — tabular numerals, consistent decimal places, explicit "per year" — you already have (`font-variant-numeric: tabular-nums` throughout `style.css`).

**4 — Loading.** 5–30 s is a >10 s problem: staged contextual text with counts, immediate button-state receipt, feedback in the region being replaced, no overlay, reassurance if it overruns, and error recovery in place. The most actionable finding is Conrad et al. 2010 — *framing* progress as fast-early nearly halves abandonment (11.3% vs 21.8%), a larger effect than the choice of indicator type.

**5 — Plotly.** The lockdown is `dragmode: false` + `fixedrange: true` + `displayModeBar: false` + `doubleClick: false` + `showTips: false` + `showAxisDragHandles: false`. `staticPlot: true` is the trap — it deletes hover and click. `scrollZoom` already excludes cartesian by default (`dflt: 'gl3d+geo+map'`), so wheel-zoom was never on. `hovermode: 'closest'` for the frontier scatter, `'x unified'` for the three time series. Touch hover and screen-reader support are both broken upstream and unlikely to be fixed — which is why a click-driven detail panel (you have one: `#pointcard`) plus a `<details>` table is the right architecture, not a workaround.

---

## Sources

**Response time, progress, waits**
- [NN/g — Response Times: The 3 Important Limits](https://www.nngroup.com/articles/response-times-3-important-limits/)
- [NN/g — Progress Indicators Make a Slow System Less Insufferable](https://www.nngroup.com/articles/progress-indicators/)
- [NN/g — Designing for Long Waits and Interruptions](https://www.nngroup.com/articles/designing-for-waits-and-interruptions/)
- [NN/g — Visibility of System Status](https://www.nngroup.com/articles/visibility-system-status/)
- [NN/g — Button States: Communicate Interaction](https://www.nngroup.com/articles/button-states-communicate-interaction/)
- [Conrad, Couper, Tourangeau & Peytchev — The impact of progress indicators on task completion, *Interacting with Computers* 22(5):417–427, 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2910434/)
- [Apple HIG — Progress indicators](https://developer.apple.com/design/human-interface-guidelines/progress-indicators)
- [GitHub Primer — Loading pattern](https://primer.style/ui-patterns/loading)

**Skeletons vs spinners (both sides)**
- [NN/g — Skeleton Screens 101](https://www.nngroup.com/articles/skeleton-screens/)
- [Viget — A Bone to Pick with Skeleton Screens](https://www.viget.com/articles/a-bone-to-pick-with-skeleton-screens/)
- [Wroblewski — Mobile Design Details: Avoid the Spinner](https://www.lukew.com/ff/entry.asp?1797)
- [Mejtoft, Långström & Söderström — The effect of skeleton screens, ECCE 2018](https://dl.acm.org/doi/10.1145/3232078.3232086)

**Onboarding & progressive disclosure**
- [NN/g — Onboarding Tutorials vs. Contextual Help](https://www.nngroup.com/articles/onboarding-tutorials/)
- [NN/g — Mobile Tutorials: Wasted Effort or Efficiency Boost?](https://www.nngroup.com/articles/mobile-tutorials/)
- [NN/g — Instructional Overlays and Coach Marks for Mobile Apps](https://www.nngroup.com/articles/mobile-instructional-overlay/)
- [NN/g — Onboarding: Skip it When Possible](https://www.nngroup.com/videos/onboarding-skip-it-when-possible/)
- [NN/g — Banner Blindness: The Original Eyetracking Research](https://www.nngroup.com/articles/banner-blindness-original-eyetracking/)
- [IxDF — Progressive Disclosure](https://ixdf.org/literature/topics/progressive-disclosure)
- [Carbon Design System — Empty states](https://carbondesignsystem.com/patterns/empty-states-pattern/)
- [Appcues — SaaS user onboarding (demo-data pattern)](https://www.appcues.com/blog/saas-user-onboarding)

**Jargon, tooltips, labeling**
- [NN/g — Why So Many Info Tips Are Bad (and How to Make Them Better)](https://www.nngroup.com/articles/info-tips-bad/)
- [NN/g — Tooltip Guidelines](https://www.nngroup.com/articles/tooltip-guidelines/)
- [NN/g — Using the Title Attribute](https://www.nngroup.com/articles/title-attribute/)
- [Morningstar — Glossary of investing definitions](https://www.morningstar.com/help-center/morningstars-approach-to-investing/glossary-of-investing-definitions)
- [Schwab — Investing glossary](https://eac.schwab.com/equity101/investing101/investing-resources/glossary)
- [Urban Institute — Three Ways to Annotate Your Graphs](https://urban-institute.medium.com/three-ways-to-annotate-your-graphs-d140e04e48ec)
- ["Click or not: different mouseover effects may affect clicking-through rate while browsing interactive information visualization" (2019)](https://www.researchgate.net/publication/336054437_Click_or_not_different_mouseover_effects_may_affect_clicking-through_rate_while_browsing_interactive_information_visualization)

**Consumer finance chart behavior**
- [Apple Support — Check stocks on iPhone (touch-and-hold; range tabs, no zoom)](https://support.apple.com/guide/iphone/check-stocks-iph1ac0b1bc/ios)
- [Yahoo Finance — Change the time period and scale on charts](https://help.yahoo.com/kb/period-scale-screen-charts-yahoo-finance-web-sln28287.html)
- [TradeStation — Mobile charts (tap to select, hold for crosshair)](https://www.tradestation.com/insights/2026/07/01/new-mobile-charts/)
- [amCharts 5 — Cursor / crosshair](https://www.amcharts.com/docs/v5/charts/xy-chart/cursor/)

**Plotly.js**
- [Configuration options](https://plotly.com/javascript/configuration-options/) · [Layout reference](https://plotly.com/javascript/reference/layout/) · [Disable zoom events](https://plotly.com/javascript/disable-zoom/) · [Event handlers](https://plotly.com/javascript/plotlyjs-events/) · [Range slider and selector](https://plotly.com/javascript/range-slider/)
- Source: [plot_config.js](https://github.com/plotly/plotly.js/blob/master/src/plot_api/plot_config.js) · [layout_attributes.js](https://github.com/plotly/plotly.js/blob/master/src/components/fx/layout_attributes.js) · [graph_interact.js](https://github.com/plotly/plotly.js/blob/master/src/plots/cartesian/graph_interact.js) · [dragbox.js](https://github.com/plotly/plotly.js/blob/master/src/plots/cartesian/dragbox.js)
- Issues: [#2844 mobile page scrolling](https://github.com/plotly/plotly.js/issues/2844) · [#5251 touchstart intervention](https://github.com/plotly/plotly.js/issues/5251) · [#1967 tap-to-hover regression](https://github.com/plotly/plotly.js/issues/1967) · [#6920 screen-reader SVG accessibility](https://github.com/plotly/plotly.js/issues/6920) · [#4264 keyboard accessibility](https://github.com/plotly/plotly.js/issues/4264) · [#1847 click/hover/selection styles](https://github.com/plotly/plotly.js/issues/1847)
- [Forum — Disable zoom but keep click enabled (maintainer answer)](https://community.plotly.com/t/disable-zoom-but-keep-click-enabled/10492)

**Accessibility**
- [MDN — aria-busy](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-busy)
- [MDN — aria-live](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Reference/Attributes/aria-live)
- [W3C ARIA APG — Alert pattern](https://www.w3.org/WAI/ARIA/apg/patterns/alert/)

---

*Two notes on process. The session's web-search budget (200 calls) was exhausted during this research, so a few threads — Vanguard/Fidelity retail chart specifics, Growth.Design's own case-study library, Wealthfront/Betterment jargon UI — are argued from adjacent sources rather than direct observation; they're the weakest-sourced claims here. And the working tree is dirty: `app.js`, `account.js`, `style.css`, and `index.html` all have uncommitted changes that this report treats as the current state.*
