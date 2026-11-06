# Sponsor a Salah — 6 November 2026 QA hardening

## Implemented in this change
- Explicit custom sponsorship token input; no silently preselected ₹25,250 value.
- Search active promoters by name/mobile across the entire organization instead of the first 100.
- All-results, multi-page, CSV-formula-safe exports for Prospects, Promoters, Collections receipts, Payout plans and actual Payout payments. Exports are limited to 50,000 rows and stop on incomplete/inconsistent pages.
- Clarified audited incoming collection corrections; visible receipt history and corrected empty-table geometry.
- Audited outgoing payment reversal with a retained original record, idempotent request ID, reason, actor, DB constraints and active-only unique period. Reversal changes the CRM ledger only, not real bank funds. One-time erroneous obligations are voided; recurring obligations can be re-attested with a corrected reference.
- API-enforced owner/CRM/finance/messaging/viewer roles and owner staff management. Existing admins migrate to owners; non-owner privileges are scoped and deactivation revokes sessions.
- 320px header/IST clock adjustments, focus-trapped Escape-dismissible mobile drawer, larger touch target areas, improved tiny-text contrast and compact mobile dashboard.
- Monthly Saasyto reminder capacity guard. At configured provider-approved sending pace, if an approved run cannot finish during its IST reminder day, it **does not enqueue any recipients** and records a failure audit event. Delivery is never silently accelerated.

## Release requirements still requiring external evidence
- Do not enable live WhatsApp. Verify Saasyto sender ownership, consent, approved templates, OTP, receipts/acknowledgements, STOP/re-consent, signed delivery receipts, rate limits and provider retry behavior against a controlled live pilot. The capacity guard prevents unsafe overpromising; it does not increase actual sender throughput or deliver missed reminders.
- Do not claim Foundation data are production-live. Deploy to isolated TLS-enabled PostgreSQL staging, measure real backup and restore, monitoring, transaction evidence and owner approval. Synthetic CI checks are not a production runbook substitute.
- Confirm financial policy with Foundation signatory for payout correction authority and evidence requirements. This application does not initiate bank transfers.
- Owner must enable main branch protection and require the full CI/review gates independently.
- The new exports are administrative records with masked references and need data-retention/handling policy approval for personal-data downloads.

## Acceptance tests
- Backend synthetic tests include multi-role enforcement, cross-tenant isolation, finance correction, net ledger, and monthly capacity guard.
- Browser tests include custom amount choice, mobile Escape navigation, and narrow viewport overflow, in addition to existing auth/CRM/finance/communication flows.
- Use `apps/api`: `python -m ruff check .`; `python -m pytest -q`; PostgreSQL Alembic upgrade and restore.
- Use `apps/web`: `npm test`, `npm run typecheck`, `npm run build`, `npx playwright test`.
- Keep only `main` after squash-merging the reviewed CI-green PR, not before.
