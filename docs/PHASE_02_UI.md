# Phase 02 — Approved web UI system

## Scope and status

This phase creates the shared, responsive Next.js presentation layer based on the two approved October 12 desktop UI boards in `docs/DESIGN_LOCK.md`. This is a **non-production preview**, not an authenticated application. The business backend has not been wired into these screens.

**Routes:** `/login` (disabled login UI), `/dashboard` (empty KPI placeholders), `/prospects` / `/prospects/inactive` / `/prospects/all`, `/promoters` / `/promoters/active` / `/promoters/all`, `/collections` / `/collections/active` / `/collections/all`, `/payouts` / `/payouts/active` / `/payouts/all`, `/reminders` / `/reminders/whatsapp` / `/reminders/email`, `/settings`.

## Architecture

- `components/ui/icon.tsx`: decorative icon set.
- `components/ui/primitives.tsx`: shared page header, horizontal tabs, form controls, panels, empty data tables, inactive buttons.
- `components/app-shell.tsx`: coherent desktop sidebar, collapse, mobile drawer, focusable skip link.
- `components/module-workspace.tsx`: declared module layouts from tab/form/table definitions.
- `app/[module]/[[...view]]/page.tsx`: Next.js route validation.
- `app/globals.css`: fonts, tokens and responsive design.
- `e2e/phase-02.spec.ts`: browser checks for real navigation, responsive behavior and disabled controls.

## Visual lock

Use Bricolage Grotesque 700 for page headings, 600 for section/card headings, Poppins 400 for descriptions, 500 for navigation/labels/buttons, 400–500 for tables, 600 for financial figures. Deep forest green `#075943`, warm white, pale mint, quiet grey boundaries. No bottom navigation. Mosque motifs remain limited to decorative sidebar/login CSS silhouettes.

## Safety of preview

No real Admin sign-in, message sending, bank uploads, or collection saves exist in Phase 02. These controls are visibly disabled and preview notices are present. Dashboard figures use em dashes, not invented monetary totals. Production data integration belongs in phases 03–12.

## Verification

Run from `apps/web`:
```bash
npm ci
npm test
npm run typecheck
npm run build
npm install --no-save --no-package-lock @playwright/test@1.56.1
npx playwright install chromium
npx playwright test
```

CI runs Chromium browser smoke tests for desktop and mobile. Pixel-perfect snapshot comparison with the approved graphic boards and assistive-technology audits still require stakeholder visual review before production.

## Exit criteria

- All approved module routes and horizontal tabs reachable.
- Single shared design system and desktop/mobile navigation.
- Keyboard-accessible navigation, proper link active state, skip link, responsive CSS and reduced-motion support.
- No misleading functional financial or sign-in actions.
- CI passes; stakeholder visual review before Phase 03.
