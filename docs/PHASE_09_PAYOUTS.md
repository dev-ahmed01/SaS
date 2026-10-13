# Phase 09 — Payout obligations and outgoing payment history

## Scope and approved navigation

The Foundation's locked **Payouts → Add Payout / Active / All** tabs now use real organization-scoped PostgreSQL records. The website stays Admin-only, responsive, warm-white/pastel mint/forest-green, with Bricolage Grotesque headings and Poppins copy. No additional sidebar module or dashboard KPIs were added.

### What counts as a payout

**Creating a payout plan does not send money.** The app has no bank transfer, UPI debit, payment gateway or outward disbursement integration.

- A **recurring payout** is a fixed INR amount owed each calendar month starting from an IST month; only the Admin can schedule status changes.
- A **one-time payout** is a fixed amount scheduled for one date. It stays visible in All (including after Admin records that the money was paid). One-time payouts never appear as recurring Active.
- **Record paid** is a distinct confirmation that Foundation funds have already been disbursed outside the app, with a unique bank/UPI/cash/cheque reference. This is **Admin-attested**, not independently bank verified.
- The app never auto-marks a plan paid just because a scheduled payment date passes.

### Financial data model

Migration `0008_payouts` creates three new tenant-scoped tables:

1. `payout_plans`: payee, purpose, notes, cadence, positive amount in integer paise, enrollment month and optional one-time date, Admin who created it, idempotency request/hash.
2. `payout_plan_terms`: effective-month history of recurring status (active/paused/closed). Scheduling a pause, resume or closure only affects **next calendar month in Asia/Kolkata** and cannot rewrite earlier monthly obligations. Close is terminal. A unique organization/plan/month constraint rejects contradictory scheduled changes.
3. `payout_payments`: immutable Admin-attested actual disbursement with plan, month, date, exact contracted amount, method, masked unique reference, idempotency request, and Admin attribution. One disbursement per plan/month, and one per one-time plan. Amount is derived from the plan, not trusted from a browser POST.

All writes occur in protected FastAPI transactions with audit events. Tenant-safe composite foreign keys protect plan references. PostgreSQL CHECK/UNIQUE constraints protect cadence, methods, positive amounts, duplicate monthly payments and references.

### Business policies

- **Recurring Active** shows currently active monthly payout plans only.
- **All** includes recurring Active/Paused/Closed plus one-time Scheduled/Overdue/Paid. The selected IST accounting month determines the monthly commitment and attested payment amount, but current status is evaluated as of today IST.
- Pause, resume and close changes become effective next calendar month. An existing next-month change cannot be silently overwritten; repeated identical requests are idempotent.
- No partial outgoing installments, advance disbursement, payout amount edits, cash refund/void, or payments for future months are supported in this phase. Admin-attested money is **never silently deleted**. Correction/reversal controls for outgoing disbursement require separate finance sign-off before production.
- The `payout_payments` record shows an Admin-attested outgoing payment; the system does not claim a bank independently verified it. The original payment reference is hashed for uniqueness and masked in API/UI responses.
- Payee names and purposes are user-entered business data, not hardcoded classifications. There is no payment provider or sender credential in code.

### API

- `POST /v1/payouts/plans`: Admin, CSRF, required request UUID; create recurring/one-time plan.
- `GET /v1/payouts/plans?view=all|active&month=YYYY-MM&offset=0&limit=20`: tenant-scoped actual commitments with paid amounts and status.
- `POST /v1/payouts/plans/{id}/status`: Admin-only effective-next-month pause/resume/close, idempotent.
- `POST /v1/payouts/plans/{id}/payments`: Admin attestation of actual outgoing funds only; exact plan amount, month, date, method/reference and true-only confirmation.
- `GET /v1/payouts/payments`: paginated tenant-scoped history; optional plan_id.
- `/api/admin/payouts/[...segments]`: explicit, allowlisted same-origin Next.js gateway for only these routes with CSRF forwarding, UUID path validation, bounded query/body and disabled caching.

### Verification and go-live gates

Backend validation: authentication, CSRF, date restrictions, future plans, recurring/one-time distinction, idempotency, reference deduplication, effective-month status history, never counting obligations as paid, organization isolation and immutable audit trail.

CI: Ruff, backend tests, SQLite Alembic upgrade/downgrade, PostgreSQL upgrade/autogenerate drift and DB constraints, Next.js typecheck/build, authenticated desktop/mobile browser journeys.

**Business decisions still pending:** payee classification (if desired), payout approval limits, whether dual-approval is mandatory for outward payments, what evidence the Admin should retain, whether amounts can change per recurring payout, advance/partial or late-disbursement policy, and audited correction/refund workflows for mistaken outgoing payments. No real Foundation transfers should be recorded until these and backup/UAT procedures are accepted.

**Next:** Phase 10 reminder eligibility (sponsors unpaid for current IST month, promoters consolidated on 20th, suppress when Inactive); Phase 11 consent-safe Pabbly/WhatsApp messages. No bank-statement importer is required under the revised Foundation plan.
