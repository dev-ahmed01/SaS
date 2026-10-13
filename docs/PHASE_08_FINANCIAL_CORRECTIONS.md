# Phase 08 — Audited collection corrections and financial review

## Intent

The Foundation uses **manual Admin-entered payment records**, not bank statement imports. Phase 08 makes mistakes correctable without deleting or silently rewriting the evidence that has already been entered.

**Reversal means voiding an incorrect accounting entry. It is NOT a refund, repayment, chargeback or outward transfer of money.**

## Approved UI preservation

Keep the locked responsive desktop website, light white/pastel sage-green/dark forest-green palette, Bricolage Grotesque headings and Poppins copy, and the approved sidebar. No extra module or tab.

- **Collections → Add:** continues to record new Admin-attested payments and show recent receipts.
- **Collections → All:** shows the actual monthly INR accounting ledger followed by **Collection history**. Admin can paginate/filter by month, see masked receipt references, and distinguish Recorded from Reversed.
- An active receipt exposes a **Reverse entry** action. The review dialog shows sponsor, amount, month and masked reference. The Admin selects a predefined reason and types **REVERSE** before confirming. Already reversed entries have no repeat action.
- A successful correction reloads the net monthly accounting and displays that an unsent WhatsApp acknowledgment was suppressed.

## Financial invariants

- Migration `0007_manual_reversals` adds the append-only `manual_collection_reversals` table.
- A reversal references exactly one immutable original `manual_collections` entry, via tenant-safe composite FK. A partial reversal is not supported: it voids the entire mistaken receipt.
- The database enforces one reversal per original collection and one reversal request ID per organization. API allows safe repeat of the **same** request (HTTP 200), rejecting different requests for the same already-reversed collection (409).
- Financial projections exclude credits whose original `manual_collections` rows have reversals. The original credit, receipt, reference digest, audit entry and message intent **remain in the database**. Receipt references stay reserved after reversal so they cannot silently double-count.
- Payment date and accounting period remain IST-based, amounts integer paise; changing a previous month can re-evaluate today's two-missed-month sponsor inactivity status. Archived sponsors remain archived.
- A pending `collection_recorded` outbox event is changed from `awaiting_integration` to `suppressed` with `collection_reversed` as the reason, in the same DB transaction. Previously suppressed/no-consent events stay suppressed. No WhatsApp network delivery runs in Phase 08.
- Backend scopes all operations by organization and requires authenticated Admin + CSRF; same-origin Next.js gateway permits only POST on a concrete UUID route.
- Audit metadata records collection ID, reason code, amount, previous/current sponsor status and message suppression, without donor phone or bank reference in audit JSON.

## Endpoints

- `POST /v1/collections/{collection_uuid}/reverse`, with `request_id` (UUID), `reason_code` (predefined enum), and `confirmation: "REVERSE"`.
- `GET /v1/collections` now returns `reversed` and `reversal_reason` for each original payment while preserving original evidence and pagination.
- `GET /v1/accounting/overview` and `POST /v1/accounting/refresh-statuses` calculate using **net non-reversed credits** rather than gross historical receipts.

## Checks and deployment boundaries

Tests must verify: credit preserved but removed from net totals; outstanding rises after reversal; reversing one valid ₹250-tier receipt leaves all other immutable receipts intact; sponsor status returns to New or Inactive according to calendar rules; original WhatsApp intent is suppressed; no cross-org data access; no CSRF bypass; idempotent retries; unknown reasons blocked; one reversal per collection; archived sponsors stay archived; post-migration PostgreSQL constraints; and responsive browser review/confirmation.

Live sending remains **disabled** until WhatsApp Business sender/approved templates/explicit consent/Pabbly connection/callback validation and a safe queued-event release policy are built and approved. A reversal does not send a donor notification or recover money.

**Financial governance still requires Foundation decisions**: proof required to record incoming UPI/cash payments, who may authorize reversals, whether a second reviewer is required for large entries, and proof and operator reconciliation standards for accepting valid ₹250-tier receipts. The initial single-Admin flow is a technical baseline, not final policy approval.

Future Phase 09: recurring and one-time payouts. Phase 10: reminder eligibility. Phase 11: Pabbly/WhatsApp confirmations and monthly reminders. No bank importer is part of the current agreed plan.
