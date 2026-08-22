# ADR 0003 — Server-rendered Django + vanilla JS; no frontend build step

Date: 2026-08-22 · Status: accepted

## Context

Condor is heading for a small release (~5 trusted users) followed by
feature/content growth (Learn pages, Compete, saved portfolios) and a
branding pass. Question: adopt a frontend stack (React/Vue + bundler,
Tailwind, etc.) now, or stay with Django templates + vanilla JS + CSS
custom properties?

## Decision

Stay with the current stack:

- **Django templates** for pages (template inheritance = one place for
  header/nav/branding once `base.html` exists).
- **Vanilla JS** per page, talking to JSON endpoints; Plotly (vendored)
  for charts.
- **CSS custom properties** as the design-token system (docs/BRANDING.md);
  no preprocessor.
- **No bundler, no npm.** `pip install -r requirements.txt` and
  `runserver` remains the entire toolchain.

## Why

- The rebranding requirement is met by tokens + an assets folder —
  a framework adds nothing to that.
- Feature growth here means more *pages and endpoints* (Learn content,
  Compete views), which is Django's home turf, not more *intra-page
  interactivity* — the Explorer is the one rich page and it's built.
- Every added toolchain is a tax on a part-time project: node versions,
  lockfiles, build breakage. Zero build step keeps the barrier to
  contribution (and to future-you) at "clone, venv, run".

## When to reopen

- A page genuinely needs heavy client-side state (live collaborative
  features, complex editors).
- More than ~3 people regularly develop the frontend and component
  reuse becomes the bottleneck.

If reopened, the JSON endpoints are already the API a SPA would need —
nothing about today's choice blocks the migration.
