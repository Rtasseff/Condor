# Branding & theming — how to restyle Condor without touching logic

Goal: when the brand lands (logo, palette, fonts), applying it is a
matter of editing **one CSS block and one assets folder** — no JS or
Python changes, no build step.

## The single source of truth

All colors live as CSS custom properties in the `:root` block at the top
of `web/explorer/static/explorer/style.css` — the *theme block*. Nothing
anywhere else may hardcode a color:

- CSS rules use `var(--token)` only.
- The chart palette in `app.js` reads the same tokens at runtime via
  `getComputedStyle` (see "chart bridge" below) — change the theme
  block, the Plotly chart follows.

Token vocabulary (keep these names; change only values):

| Group | Tokens |
|---|---|
| Surfaces | `--plane` (page), `--surface` (cards/chart), `--surface-2` (raised) |
| Text | `--ink`, `--ink-2`, `--muted` |
| Chart chrome | `--grid`, `--axis`, `--ring` |
| Brand accent | `--accent`, `--accent-hi` |
| Data series | `--series-frontier`, `--series-cal`, `--series-you` |
| Signals | `--danger` |

Rules for choosing values:

- Data-series colors must stay distinguishable under color-vision
  deficiency **against the chosen surface** (the current set was checked
  for CVD on the dark surface; re-check if surfaces lighten).
- Contrast: body text (`--ink` on `--surface`) ≥ 7:1, secondary
  (`--ink-2`) ≥ 4.5:1.

## Fonts

Two tokens, declared in the theme block and used everywhere:

    --font-body:    system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --font-display: var(--font-body);   /* headings/wordmark; may diverge */

When brand fonts are chosen: put `.woff2` files in
`web/explorer/static/explorer/fonts/`, add `@font-face` rules at the top
of `style.css`, and change the two tokens. Self-host — no Google Fonts
CDN (privacy + offline dev).

## Logo & assets

`web/explorer/static/explorer/brand/` is the assets folder:

- `logo.svg` — header wordmark/mark (referenced from the base template).
- `favicon.svg` / `favicon.png`.
- Anything else visual (empty-state art, etc.).

Swap the files, keep the names → the app rebrands.

## Layout for growth

The moment a second page exists (Learn, Compete, saved-portfolio pages),
extract `base.html` (header, nav, theme includes) and make pages extend
it — branding then lives in exactly one template. Until then the single
`index.html` is fine.

## What we deliberately did NOT adopt

No CSS framework, no frontend build step (React/Tailwind/bundlers) — see
docs/decisions/0003. At this scale, tokens + template inheritance give
the same "change once, applies everywhere" property with zero toolchain.


## Current brand (executed 2026-08-29)

- **Faces:** IBM Plex Sans (400/500/600/700) for display + UI, IBM
  Plex Mono (400/500) for money, tickers, and numeric table columns.
  Self-hosted woff2 (latin) in `static/explorer/fonts/` under the SIL
  Open Font License (`OFL-*.txt` alongside — keep them; the license
  requires it when redistributing). Zero external font hosts, zero
  recurring cost.
- **Mark (v2, 2026-08-29 — RT: "no condor?!"):** `brand/logo.svg` —
  original artwork of an actual soaring condor seen from below: broad
  white wings with the fingered primaries every condor silhouette
  shows, tips swept in the chart's own blue→teal series colors, teal
  ruff, small head, silvery wedge tail. Iterated visually at 128/64/
  26px and favicon sizes. `brand/favicon.svg` is the bird on the
  surface tile. Rebranding remains: replace these two files + token
  values.
- **Depth language:** layered radial glows on the body (teal/blue at
  ≤7% alpha), inset top-light + soft shadow on cards, gradient primary
  buttons with hover lift, focus-visible rings in `--accent-hi`.
- **Numerals:** all money/percent cells use Plex Mono +
  `tabular-nums` (tiles, tables, weight bars).
- Charts read `--font-body` via `cssVar` — Plotly follows the brand
  automatically.
