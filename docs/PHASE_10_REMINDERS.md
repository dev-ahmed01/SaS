# Phase 10 — IST Reminder Eligibility and Prepared Queue

## Purpose and scope

This phase implements read-only eligibility previews, deduplicated **preparation only** and audited recipient snapshots for the approved Foundation workflow:

- On the **configurable sponsor reminder day (initially the 5th)**, a sponsor with an unpaid current-month contribution may be eligible for **one** WhatsApp reminder.
- On the **configurable promoter follow-up day (initially the 20th)**, a promoter may be eligible for **one combined WhatsApp summary**, listing eligible unpaid sponsors assigned to that promoter.
- After **two fully missed completed months** (or current Admin-configured inactivity threshold), a sponsor becomes **Inactive** and is excluded from both direct reminders and promoter follow-up summaries. Eligibility is calculated from the **net financial ledger**, not the cached lifecycle status; reversed entries never count as paid.
- A sponsor whose current month is fully paid is **not eligible**, even if the sponsor is otherwise Active. Valid ₹250-tier receipts reduce the outstanding balance; an account may remain unpaid against its current monthly commitment even after reactivation. No sub-₹250 or off-tier new manual collections are allowed.
- Sponsors may register before first payment. New unpaid sponsors **with WhatsApp consent** are eligible for the direct reminder until they reach the inactivity threshold. This is a first-release policy requiring Foundation review.
- A promoter must be **Active**, have recorded WhatsApp consent, have a usable contact number, and have a current assigned eligible unpaid sponsor for the combined summary. Assignment is the Foundation's current operational authorization for promoter follow-up; confirm sponsor/promoter information-sharing policy before any delivery.

## IST and scheduling

All calculation uses **Asia/Kolkata**, with full calendar months. The reminder day is loaded from `OrganizationSettings` — **never hardcoded** in the engine. No expired-day catch-up or backdating is permitted.

`GET /v1/reminders/preview?kind=sponsor|promoter` works on any day for authenticated Admin preview. It returns the upcoming/current monthly configured reminder date, eligible recipient list, total outstanding balance and eligible sponsor count. No mutation, no sending.

`POST /v1/reminders/prepare` requires a live Admin session and CSRF token, and accepts a kind and unique request UUID. It can run **only on the configured IST reminder day**. It re-runs eligibility within the transaction, serializes organization writes, and records exactly one batch per kind/month, one recipient intent per sponsor or promoter, and an audit event. Empty eligible batches are valid, record zero intents and are still idempotent.

`GET /v1/reminders/batches` reads the organization-scoped preparation history. The UI lives inside the approved **Reminders → WhatsApp Reminder** screen, with sponsor/promoter controls and a read-only recipient preview. The action is deliberately labeled **Prepare batch (do not send)**, never Send.

There is **no autonomous timer or cron dispatch in this phase**. Phase 11 adds a controlled scheduler, WhatsApp Business, approved templates, Pabbly orchestration and real delivery status.

## Privacy, deduplication and delivery safety

- Data model: `reminder_batches` plus `reminder_intents` (Alembic revision `0009_reminder_intents`). The records hold organization-scoped recipient IDs, month, count, outstanding paise, minimal ID/amount snapshots and `prepared` state.
- DB composite foreign keys prevent cross-organization recipient/batch links. Unique org/kind/month batch and org/recipient/kind/month intent constraints prevent duplicate preparation.
- Snapshots store **no phone numbers, full payment references or messages**. API preview returns names to the authenticated Admin only.
- **No messages are sent**; the only intent state is `prepared`, with `delivered_count=0`. Existing Phase 7 collection-confirmation outbox events remain separate.
- `current_intent_eligible(...)` is a conservative pre-dispatch policy gate: it must revalidate organization, consent, current month, schedule day, Active/New status, net outstanding dues, promoter activity and current assignment. Future sender must **regenerate the actual body from up-to-date recipients**, never use a stale frozen promoter sponsor list.
- Consent revocation, full payment, new inactivity, sponsor archival or promoter reassignment can make an already prepared record ineligible. The future delivery worker **must skip it**.
- Max sponsor/recipient limits fail closed, not truncate a recipient list into a misleading partial broadcast.
- No Admin page or endpoint can send WhatsApp, email or Pabbly messages yet. No sender account or contact database is provisioned.

## Testing and acceptance

Synthetic tests verify IST midnight boundaries, configurable days, no catch-up, paid/inactive/archived/no-consent exclusion, installment balances, one promoter summary regardless of assigned sponsor count, Admin/CSRF, request idempotency, current eligibility before dispatch, cross-tenant isolation, capacity fail-closed, and zero-recipient runs.

PostgreSQL tests enforce unique batch/recipient, same-org FK, and recipient-type/state constraints. Desktop/mobile browser coverage verifies actual preview contents and that no delivery control or unsanctioned endpoint is available.

## Explicit open business and release decisions

1. **Resolved by Foundation 13 October 2026:** any valid newly recorded ₹250-tier contribution reactivates a sponsor, but reminder eligibility must still recheck consent, inactivity, current outstanding balance and the allowed schedule. Direct messaging to never-paying New sponsors still requires separate approval.
2. Should new registered but never-paying sponsors receive the 5th reminder? This phase includes them **until** the two-missed-month threshold, provided consent exists.
3. Does the Foundation approve disclosing sponsor name/outstanding amount to the assigned promoter via WhatsApp? Assignment permits internal review; external WhatsApp delivery still needs sign-off and privacy/consent review.
4. WhatsApp sender/business account, Pabbly connection, approved message templates, opt-out/re-opt-in handling, webhook signatures, retry policy, delivery receipts, cost budget and old-queue release rules are pending.
5. No real sponsor data, messages, payouts or bank transfers should be used for production until security, UAT, backup/restore and operational approval.

Next **Phase 11** will implement the controlled provider transport and 5th/20th scheduler, along with collection confirmations, without bypassing these gates.
