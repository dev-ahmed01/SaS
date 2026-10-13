# Phase 07 — Manual collection entry and WhatsApp confirmation preparation

The Foundation will **enter received payments manually**. Bank statement importing and bank-specific UPI matching are deferred. The Admin confirms actual receipt of funds before recording them.

## User journey
1. **Collections → Add:** search and select an existing sponsor.
2. Enter the exact **approved ₹250 denomination** (₹250, ₹500, ₹750, …; no smaller or off-tier entries), date received, sponsorship month, method (UPI / bank transfer / cash), and unique bank transaction reference or numbered cash receipt. The Admin must not invent or round money to satisfy the rule.
3. Tick the explicit confirmation that Foundation records have been checked.
4. Save. The backend writes the collection, Admin-attested credit and audit record in one transaction.
5. The monthly ledger updates and the sponsor's current Active/New/Inactive status recalculates.
6. If WhatsApp opt-in exists, exactly one **confirmation intent** is recorded. It is **awaiting integration**, not sent. Otherwise the event is **suppressed**.

The confirmation must say "The Foundation has recorded your contribution of ₹X for [month]" rather than claiming independently verified bank settlement. Sending begins only after approved WhatsApp Business/Pabbly onboarding.

## Controls and APIs

- `POST /v1/collections` is Admin session + CSRF only. A valid idempotency `request_id` prevents double credit from retries. A unique normalized reference digest prevents different requests double-counting the same transaction even if its payment method is relabeled. Never store or return the full reference.
- `GET /v1/collections` is paginated and organization-scoped. Entries are **immutable**; Phase 08 adds append-only audited full reversals for incorrectly recorded collections, never a silent edit.
- `verified_credits.source_type = manual_attested`, not `bank_reconciled`. All amounts are integer paise.
- `message_outbox` has one `collection_recorded` intent per collection, with `awaiting_integration` or `suppressed`. **No provider request is sent in this phase.**
- The same-origin Next.js gateway allowlists only GET and POST, with JSON, CSRF forwarding and origin restrictions.
- Date validation prohibits future months and payments recorded before enrollment.

## Remaining production acceptance gates
- Full verification evidence standard for UPI, cash and bank transfer, and who may reverse/correct a mistaken payment.
- **Resolved 13 October 2026:** every valid ₹250-tier newly recorded contribution immediately reactivates an inactive sponsor; there is no partial-contribution feature. Historical off-tier receipts remain immutable and auditable. Migration 0013 blocks NEW off-tier database inserts without rewriting old evidence.
- WhatsApp Business sender, approved template, explicit permission to contact donors, Pabbly integration, signed callbacks, deduplicated delivery, opt-out support and monitoring. Do not automatically release the existing pre-integration backlog.
- Security/UAT, migration verification, backups, production monitoring and audit trail review.

This is a **staging/development feature** until the gates above are accepted.
