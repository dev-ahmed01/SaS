# Communication CRM — design, controls and delivery boundary

## Product intent

The original **Reminders** screen displayed system preparation history, provider counters and
single-purpose sponsor/promoter day previews. The approved replacement is **Communication**,
a reusable workspace for Admin to communicate with prospects, promoters or both.

The three navigation views are **Compose**, **Campaigns**, and **Templates & Automations**.\nThe combined last view stacks the two independent protected workflows vertically,\nwithout a right-hand sidebar. The previous /communication/automations URL redirects.
There is no preparation-history table in the new UI. Legacy `/reminders`,
`/reminders/whatsapp`, and `/reminders/email` redirect to `/communication`.

## Design references (October 2026)

- Customer.io explains **broadcasts** as audience + message + one-time/scheduled trigger,
  and **automations** as event/segment/date-driven workflows:
  https://docs.customer.io/messaging/send/types-of-automations-and-broadcasts/
- Customer.io's campaign setup stresses the four reusable dimensions: trigger, audience,
  timing and message: https://docs.customer.io/get-started/send-messages/
- Twilio SendGrid promotes dynamically filtered contact segments and suppression:
  https://www.twilio.com/docs/sendgrid/ui/managing-contacts/segmenting-your-contacts
- WhatsApp business-initiated outreach generally requires opt-in and a pre-approved
  template outside a 24-hour customer-service window:
  https://www.twilio.com/docs/whatsapp/best-practices-and-faqs

**SaS-specific choices:** Administrative rather than marketer-style UI; no inbox/chat
fiction, no huge vanity metrics, no claims of delivery from provider acceptance.
A draft remains a draft even if it has an IST schedule. A campaign can have a
WhatsApp provider template ID, but the ID alone never proves Meta approval.

## Implemented behavior

1. **Compose:** audience (prospects, promoters, both); segment (all, active,
   inactive, unpaid); channel (WhatsApp, Email); message category, body, optional
   saved template, schedule in IST; live sample of consent-eligible recipients.
   Save produces a durable **draft** or **planned** campaign and no transport work.\n   The right-hand audience and message previews were removed from the UI; actual\n   permission checks remain in the backend and simulation-only review service.
2. **Templates:** versioned add/edit/soft-archive, with separation between
   template copy and provider template ID. Referenced automation templates
   cannot be archived without removing the rule.
3. **Campaigns:** saved snapshots, scheduled IST date, eligible count at creation
   (not a send-time guarantee), cancellation, and audit trail.
4. **Automations:** create/delete reusable **inactive** trigger definitions
   (monthly sponsor 5th IST, promoter 20th IST, payment recorded, prospect stage
   changed, scheduled date, manual event). Existing approved 5th/20th reminder
   rules remain unchanged; new definitions never silently activate.
5. **Real-time date:** authenticated backend `/v1/communication/clock` returns
   `now_ist` from server UTC time. The sidebar header clock synchronizes on mount
   and when tab becomes visible, and updates every 15 seconds. The time is
   formatted using `Asia/Kolkata`, independent of device timezone. On lost
   server contact the fallback uses device time in IST and marks the warning
   in its tooltip. Historical financial dates remain ledger-derived.

## Safety

- All workspace endpoints require authenticated Admin session; state changes
  require CSRF and same-origin Next.js gateway checks.
- No public `send` route exists for these campaigns.
- Recipient preview checks actual opt-in, rejects archived contacts,
  deduplicates matching WhatsApp numbers across roles, applies Active/Inactive
  and verified-ledger unpaid filters, and caps audience processing. Recipient
  details are never publicly exposed.
- Email contact records have **no email-send consent field** in the current
  schema, so email compose works for drafts but email recipient
  `eligible_count` is **zero**. Do not infer consent from a stored address.
- Existing Pabbly payment and 5th/20th reminder transport is independently
  gated by production settings and reviewed template IDs. This new CRM cannot
  invoke that worker or replay old messages.
- A campaign's `planned_for` is **not** an executable delivery schedule.
  Business-approved channel credentials, template-approval verification,
  per-recipient permission checks, quiet hours, rate limits, idempotency,
  opt-out tracking and provider webhook reconciliation are still prerequisites
  before general-purpose outbound delivery can be enabled.
- Database migration 0016 adds isolated tables and blocks downgrade if they
  contain records, protecting drafts, history and the audit trail.

## Synthetic demo

The existing local-only opt-in command:

```powershell
cd apps\api
.\.venv\Scripts\python.exe -m app.seed_local_crm --apply --confirm-synthetic-only
```

adds four sample templates, three campaigns and two **inactive** automation
definitions alongside the existing 100 fake prospects, 10 fake promoters and
20 planned payout commitments. Sample contacts have no recorded communication
consent; no messages, receipts or provider dispatches are fabricated. It is
safe to rerun without duplicating demo rows but **must only run in an isolated,
disposable local-demo database**.

## Consent and simulation-only preparation (migration 0017)\n\n- Admin can append channel-specific grant or revoke evidence with source and proof\n  reference, without implying that stored phone/email addresses are consent.\n- Campaign recipient preflight is an idempotent, tenant-scoped dry run storing\n  one status per matching contact but **never** a send job, phone number or\n  message body. It is protected by CSRF and cannot be enabled as delivery.\n- Communication checks email proof explicitly; WhatsApp reminders retain\n  their legacy consent checkbox, while general WhatsApp outreach also requires\n  documented permission. Opt-outs suppress every contact sharing that address.\n- Existing independently approved Pabbly transport also checks these opt-outs\n  immediately before any network request. Unconfigured message providers stay off.\n- Collection external reference numbers are optional; absent references are\n  represented by internal unique ledger keys only, not invented bank evidence.\n\n## Next production milestone

With explicit approval of provider(s) and consent policy, implement an outbound
transport adapter (WhatsApp template messages; email via a verified sending
domain/provider), message-level recipient snapshots and suppression,
review/approval workflow, delivery queue with per-attempt correlation,
signed status webhooks, unsubscribe/opt-out handling and operator controls.
Do not mark either channel live solely because a campaign was saved.
