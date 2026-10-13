# Phase 06 — Monthly sponsorship accounting

## Decisions locked in

- Currency **INR**, calendar timezone **Asia/Kolkata**.
- New foundations provision at **₹500/month** (50,000 paise) per the latest client decision. Admin Settings can change this default. Previously provisioned organisations keep their existing settings: migrations **never silently rewrite agreed contributions**.
- Each prospect can register before payment, starts as **New**, and has an agreement start in their IST registration month.
- A full verified current-month contribution immediately activates/reactivates a sponsor. Missing **two fully completed consecutive months** (or Admin's configured threshold) makes a sponsor **Inactive**. A partial contribution reduces outstanding balance but does not count as a fully-paid month. If a sponsor has never fully paid and fewer than two completed months have elapsed, status remains **New**.
- Overpayment is shown under total verified credits; outstanding cannot be negative. Credit allocation or excess carry-forward is not performed automatically.
- No payment may be invented from a QR scan or a mobile SMS. No payment confirmation or receipt creation endpoint exists in Phase 06.

## Data model and invariants

- `prospects.start_month`: enrollment month, first calendar day in IST. Legacy records backfill from their actual recorded registration time. New signups set this immediately.
- `sponsorship_rates`: effective-month agreement schedule. A new signup receives a starting rate. Subsequent Admin changes to a sponsor's amount take effect **next month**, leaving current and historical rates untouched. Revisions to the same future month's plan replace that yet-to-start rate; changes are audited through Prospects.
- `verified_credits`: immutable evidence-backed amounts, with unique organization-scoped source references, positive integer paise, calendar month, explicit source, and tenant-safe composite foreign keys. Phase 07 added Admin-attested manual collection records; Phase 08 introduces audited full reversal of an incorrect manual entry. Bank import is deferred.
- `lifecycle_status`: a materialized read-model cache, not payment evidence. The deterministic policy is evaluated live for the accounting screen. Admin's **Refresh sponsor statuses** copies current evaluated values to the Prospects list, with audit history. Future Phase 10 scheduling performs this automatically and performs all reminder eligibility checks directly against ledger state, not stale caches.

## Financial semantics

For each sponsor and IST calendar month:

```
due = agreed rate effective for the month
verified = sum of verified credits allocated to that month
outstanding = max(0, due - verified)
fully_paid = verified >= due
```

Archiving a sponsor stops new recurring dues after the archive month while retaining previous months and their verified credits in historical reports.\n\nA sponsor only has dues from the agreement start month. All report totals use **integer paise** until presentation, never binary floating-point money. A verified credit may reference a past month, but its `verified_at` timestamp must not be later than the report's evaluation time. The selected month identifies the due period; the sponsor status displayed is the status **as of today IST**.

## Screens and API

The locked Collections tabs stay **Add / Active / All**. The **All** tab now contains the first real monthly ledger: date selector, monthly dues, verified funds, outstanding total and per-sponsor status. **Add** is implemented for Admin-attested manual collection records in Phase 07, and **Active** remains a later-release screen.

- `GET /v1/accounting/overview?month=YYYY-MM&offset=0&limit=20`: organization-scoped, bounded last 36 months, no mutation. Admin session required.
- `POST /v1/accounting/refresh-statuses`: Admin, CSRF and same-origin required; audit only genuine status transitions, idempotent at constant evidence.
- Phase 07 introduced the Admin-attested manual collection endpoint; Phase 08 introduces an audited reversal endpoint. Neither verifies a bank statement.

## Delivery and pending decisions

Test matrix includes midnight IST boundary, leap months, first enrollment, two missed months, partial/full installments, activation/reactivation, absent evidence, future-effective rate updates, tenant isolation and PostgreSQL uniqueness. GitHub CI covers migrations, lint, tests, web build and desktop/mobile E2E.

The Foundation chose manual entry in Phase 07 and audited corrections in Phase 08; the statement importer is deferred. Phase 10 adds scheduled status refresh and payment eligibility; Phase 11 connects Pabbly with WhatsApp Business after explicit opt-in and template approval.

**Operational warning:** Phase 06 is a financial *obligation and status engine*, not a payment collection or verified bank-integration release. Do not use its simulated fixtures as financial evidence or deploy to production without backup/security acceptance.
