# Phase 02 — Approved web UI system

## Scope and status

This phase creates the shared, responsive Next.js presentation layer based on the two approved October 12 desktop UI boards in `docs/DESIGN_LOCK.md`. This is a **non-production preview**, not an authenticated application. The business backend has not been wired into these screens.

**Routes:** `/login` (disabled login UI), `/dashboard` (empty KPI placeholders), `/prospects` / `/prospects/inactive` / `/prospects/all`, `/promoters` / `/promoters/active` / `/promoters/all`, `/collections` / `/collections/active` / `/collections/all`, `/payouts` / `/payouts/active` / `/payouts/all`, `/reminders` / `/reminders/whatsapp` / `/reminders/email`, `/settings`.

## Architecture

- `components/ui/icon.tsx`: accessible decorative icon library.
- `components/ui/primitives.tsx`: shared page header, horizontal tabs, form controls, panels, empty data tables, inactive buttons.
- `components/app-shell.tsx`: coherent desktop sidebar, collapse, accessible mobile drawer, focusable skip link.
- `components/module-workspace.tsx`: declared module layouts from tab/form/table definitions. Avoid independent copies of the same controls.
- `app/[module]/[[...view]]/page.tsx`: Next.js route validation.
- `app/globals.css`: fonts, tokens and responsive visual patterns.

## Visual lock

Use Bricolage Grotesque 700 for page headings, 600 for section/card headings, Poppins 400 for descriptions, 500 for navigation/labels/buttons, 400–500 for tables, 600 for financial figures. Deep forest green `#075943`, warm white, pale mint, quiet grey boundaries. No bottom navigation. Mosque motifs remain limited to decorative sidebar/login CSS silhouettes.

## Financial/authenticity safety

No real Admin sign-in, message sending, bank uploads, or collection saves exist in Phase 02. These controls are visibly disabled and preview notices are present. Dashboard figures use em dashes, not invented monetary totals. Production data integration belongs in phases 03–12.

## Verification

Run from `apps/web`:
```bash
npm ci
npm test
npm run typecheck
npm run build
```

A full pixel-level screenshot comparison and assisted-technology/browser audit require Playwright/axe installation and are a follow-up quality gate before the UI is accepted for production. Do not claim these audits passed based on source-only tests.

## Exit criteria

- All approved module routes and horizontal tabs reachable.
- Single shared design system and desktop/mobile navigation.
- Keyboard-accessible navigation, proper link active state, skip link, responsive CSS and reduced-motion support.
- No misleading functional financial or sign-in actions.
- CI passes. Screens receive stakeholder visual review before Phase 03.
