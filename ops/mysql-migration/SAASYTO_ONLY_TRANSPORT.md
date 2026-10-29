# Sponsor a Salah — Saasyto-only WhatsApp transport

Status: Development branch; not deployed or merged. No live send flags have been enabled.

## Decision and provider scope
Saasyto is the **only active WhatsApp campaign transport**. Removed Pabbly sender code, webhook routes, and secrets. Existing message_dispatches and message_delivery_events tables remain as *historical audit records*, never treated as new Saasyto receipts.

Saasyto publicly documents its own web-dashboard scheduling and suggests 90–120 seconds between personal-number messages, but does not publicly specify the API contract for this CRM's direct-send endpoint. We reuse the CRM's existing Saasyto /api/send connector and our own durable schedule and claim queue. We do not invent or call an undocumented hosted campaign-scheduling API. Gateway acceptance means accepted_unverified, not Delivered or Seen.

## Sending pathways
1. Normal marketing/information campaigns: an Admin explicitly checks eligible recipients and approves the campaign. The Saasyto worker uses at-most-once recipient claims and send-time consent checks.
2. Monthly sponsor reminders (5th IST): with a separately enabled standing monthly rule, the private worker prepares exactly one campaign per organization/month/kind, using current unpaid and opted-in contacts. It recomputes actual outstanding sponsorship on each send.
3. Consolidated promoter reminders (20th IST): one recipient per promoter, with current unpaid assigned sponsor list and amount, separate financial disclosure approval, length and privacy limits.
4. Safe outcomes: opt-outs, paid bills, historical Pabbly attempts, disabled policy, out-of-day batches and unknown attempts are not resent. Previously missed IST reminders are suppressed instead of being sent on a later date.

## Explicit approvals and switches
- Saasyto delivery, sender approval, instance/access token, approval cutoff, worker flag and independent Saasyto monthly reminder flag must all be deliberately configured.
- SAASYTO_AUTO_REMINDERS_ENABLED defaults to false, never turns itself on.
- Organization.automation_enabled requires the existing audited Admin confirmation.
- Promoter financial summaries separately require PROMOTER_DISCLOSURE_APPROVED.
- Recipient opt-in/opt-out rules, current active status and positive net unpaid amounts remain mandatory.
- Saasyto API callbacks have not been verified. Do not claim Delivered or Seen from HTTP acceptance.

## Deduplication
A namespaced UUIDv5 request key (organization/kind/IST month), unique monthly ReminderBatch constraint and per-run Saasyto recipient uniqueness prevent repeated scheduling. Each claimed attempt commits before network I/O. On crash, stale claimed attempts become Unknown and are never retried automatically. At dispatch the worker validates the matching batch, intent and day.

The manual /v1/reminders/prepare endpoint remains for historical compatibility; an existing manually prepared batch intentionally blocks creation of a second automated batch for that month. Avoid manually preparing it when automatic scheduling is expected.

## Outstanding tasks (must not be misrepresented as completed)
- Payment receipt confirmation and explicit manual resend intents stay recorded, but the removed Pabbly transport no longer delivers them. An idempotent Saasyto-only receipt path must be reviewed and implemented separately before those messages can be promised.
- Custom automation trigger definitions still do not autonomously send.
- Saasyto vendor-documented direct-send quotas, webhooks and delivery semantics are not verified.
- No InterServer test site, 24/7 worker process, actual Foundation database backup/restore, real-data copy or production deployment has been performed. Production MySQL remains blocked.

Vendor documentation references:
https://saasyto.com/product/saasyto-personal-whatsapp-subscription/
https://saasyto.com/whatsapp-personal/
