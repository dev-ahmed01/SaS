# Phase 12 — Live Foundation Dashboard

**Read-only Admin financial and operational overview; no demonstration values.** The locked Foundation palette, sidebar, Poppins and Bricolage Grotesque fonts remain unchanged.

## Sources and meanings

- Sponsor totals count nonarchived Prospects and compute New/Active/Inactive from current IST accounting, not a stale cached lifecycle field.
- Monthly sponsorship due uses each sponsor's historical effective-dated agreement. Recorded contributions include only non-reversed credit allocations for the month; receipts are **Admin-attested**, not independent bank verification.
- Outstanding sponsorship due is the unpaid portion floored at zero. An overpayment is not silently carried forward.
- Recurring payout commitments are computed from effective monthly active/paused/closed terms; one-time payout plans belong to their scheduled month. **A plan is not a payment.**
- Actual outgoing disbursements count distinct Admin-attested PayoutPayment records; bank transfers are not initiated by this app.
- Active promoters and month’s prepared reminder batches come from their actual records. Payment confirmations awaiting setup are not sent. WhatsApp delivered counts only verified provider callbacks.
- Six historical IST months show due/recorded incoming alongside planned/attested outgoing, using one bar scale. Recent activity uses actual payment, reversal, plan and reminder records.
- Archived sponsors retain applicable historical dues and receipts; reversed manual receipts are excluded from the net ledger but preserved in audit evidence.
- No totals are described as profit, bank balance, or independently bank-reconciled cash.

## API and security

`GET /v1/dashboard/overview` is protected by the Admin session, scopes every database query by organization ID and returns `Cache-Control: no-store`. `GET /api/admin/dashboard` is a same-origin Next.js proxy that accepts no query parameters and does not support writes. Dashboard has no mutation endpoints and no new DB migration.

Zero-record organizations display real zero values and an empty activity state. API/network errors display a retry prompt rather than showing invented zero balances. UI supports keyboard use, narrow/mobile screens and a manual read-only Refresh button.

## Acceptance and production gates

Test auth/tenant isolation, empty organization, IST month boundaries, sponsor registration/collection/partial and reversal, payout commitments vs recorded disbursement, pending vs provider-confirmed messaging, six-month trends, responsive desktop/mobile views, migrations and backend lint/build CI.

Phase 13 still requires ordered merging of stacked PRs, secrets and environment separation, independent financial UAT, backups/restore drills, capacity testing, visual acceptance and authorized Pabbly/Meta WhatsApp sender/templates before live messages.
