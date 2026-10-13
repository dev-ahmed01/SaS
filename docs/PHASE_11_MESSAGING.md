# Phase 11 — Controlled WhatsApp Delivery Bridge

## Design and operational status

This release integrates the Foundation's **Admin-entered collections** and its **prepared reminder intents** with a secured Pabbly Connect webhook. It does **not** provision an actual Meta WhatsApp Business account or approve templates. The entire sender defaults OFF.

The only message categories are:
1. **Payment acknowledgment**: queued when Admin explicitly attests a manually received collection (Phase 07). A reversal before dispatch suppresses the queue. Template should say *"The Foundation recorded ₹{amount} for {month}"*, not *"Bank verified"*.
2. **Sponsor reminder**: prepared only on the configured 5th (or Admin-set day) for net unpaid, WhatsApp-consenting, non-inactive and non-archived sponsors. Only recorded contributions of ₹250 or higher in exact ₹250 increments are allowed; any remaining commitment balance stays outstanding.
3. **Promoter consolidated follow-up**: prepared only on the configured 20th (or Admin-set day), at most one intent per promoter, using **live current assignments and unpaid balances**. By default the provider will not receive names/balances for a promoter until the Foundation explicitly sets `PROMOTER_DISCLOSURE_APPROVED=true` following privacy review.

The worker **re-evaluates** payment, consent, active status, current-day scheduling, the current organization's automation switch and (for promoters) linked sponsors immediately before transmitting. It never sends from a saved reminder snapshot or an Admin-modified payee string.

## No false delivery reporting

- `message_dispatches`: immutable intent linkage, one dispatch attempt per original message event, source tenant-safe. A successful Pabbly HTTP response means **accepted by provider**, NOT sent or delivered through WhatsApp.
- `message_delivery_events`: signed callback from the *approved Pabbly workflow* carrying a unique provider event ID and real Meta/WhatsApp message ID. Only this records `sent` or `delivered`.
- A provider error is `failed`; an HTTP timeout is `unknown`, **never automatically retried**: a timed-out Pabbly call might already have sent, and retrying could message twice. Operations must investigate and decide separately.
- Old saved payment confirmations or reminder batches are **never replayed** when the integration is first activated. Only intents created after the explicit `MESSAGING_ENABLE_AFTER` timestamp can be considered.
- Reversing a collection before dispatch cancels its pending acknowledgment; if a provider has already received it, reversal cannot recall or erase a delivered message. The UI preserves confirmed provider status.
- The frontend never has a "send all" control and cannot access internal worker or callback secrets. It only shows authenticated Admin readiness and truthful aggregate counters.

## Pabbly/Meta workflow contract

Your deployment administrator must create a **private** Pabbly Connect workflow with an HTTPS incoming webhook at `https://connect.pabbly.com/workflow/...`. Configure it to map JSON POST fields:

```json
{
  "correlation_id": "<unique delivery attempt UUID>",
  "idempotency_key": "<same UUID>",
  "recipient_phone": "+919876543210",
  "template": "approved_whatsapp_template_name",
  "variables": {
    "name": "Example Sponsor",
    "amount_inr": "500.00",
    "period_month": "October 2026"
  }
}
```

The variable set is different for sponsor and promoter reminders. Pabbly must verify `X-SaS-Signature`, HMAC-SHA256 over the **exact request body** using `PABBLY_SIGNATURE_SECRET`, before passing any content to Meta. Pabbly/WhatsApp must also **deduplicate `idempotency_key`**, use approved template IDs, send only to opt-in recipients and record actual provider IDs. Do not log recipient names/numbers or payment data in broadly shared automation logs.

When Meta confirms status, Pabbly may POST an event to `/internal/messaging/callback`:

```json
{
  "event_id": "stable-unique-event-reference",
  "dispatch_id": "<correlation_id>",
  "provider_message_id": "<real Meta/WhatsApp message id>",
  "status": "sent"
}
```

Allowed statuses: `sent`, `delivered`, `failed`. Header `X-SaS-Callback-Signature: sha256=<HMAC_SHA256(raw_body, MESSAGING_CALLBACK_SECRET)>` is mandatory. Unsigned, conflicting, duplicate-different and status-downgrading events are rejected. The Foundation must verify that Pabbly actually exposes and can sign delivery receipts before enabling the sender.

## Activation and runner

1. Have the Foundation approve its Meta WhatsApp Business sender, per-template variable mappings, opt-in wording, message costs, opt-out policy, contact retention and promoter disclosure.
2. Deploy the API over HTTPS with all ordinary Admin secrets, PostgreSQL and the migration `0010_message_dispatches`. Do not expose service credentials in Next.js `NEXT_PUBLIC_*` variables.
3. Put Pabbly URL and three approved Meta template names in the backend secrets manager. Generate independent **32+ character** `MESSAGING_RUNNER_SECRET`, `MESSAGING_CALLBACK_SECRET` and `PABBLY_SIGNATURE_SECRET`.
4. Set a **future timezone-aware** `MESSAGING_ENABLE_AFTER`, `MESSAGING_SENDER_APPROVED=true` and `MESSAGING_DELIVERY_ENABLED=true`. For production, the backend refuses insecure URL/secret or missing-approval configuration. Staging/development dispatch remains disallowed.
5. The Foundation separately enables organization `automation_enabled` in authenticated Settings.
6. Configure a trusted scheduler, e.g. a once-per-minute service job, to POST `/internal/messaging/dispatch` with `X-Delivery-Runner-Token` over your private HTTPS network. It is **not** a browser endpoint. Workloads are limited to 10 messages per run.
7. Require signed Pabbly callbacks, test opt-outs, reversal race cases, stale reminders, clock boundary, duplicate runs and delivery status before enabling actual donors.

**No scheduler, provider credentials or real external sender were provisioned by this PR.** Real messages will not go out until these explicit external operational steps are completed.

## Remaining safety gates

- Verify provider's genuine status receipt integration and Pabbly signature/hardening capability. A 2xx acknowledgment is not a WhatsApp receipt.
- Implement and test inbound WhatsApp opt-out/re-opt-in policy and enforce consent immediately; existing Admin opt-out is honored at send time, but real provider inbound STOP handling requires explicit Foundation and Meta workflow acceptance.
- Monitor unresolved timeouts, failed provider responses and message costs, and implement manual investigation rather than blind retries.
- Finish staging, UAT, backup/restore, outgoing payment correction authorization and complete privacy review. Do not release real contacts based on synthetic CI evidence.

## Test coverage

Synthetic tests cover disabled default, runner token, no backlog replay, opt-out and financial reversal suppression, provider HMAC signature, exactly-once claim, configured IST reminder gating, promoter disclosure approval, unknown timeout, signed callback authenticity, duplicate webhook receipt and no misleading sent/delivered counts. GitHub CI additionally checks Alembic migration drift, PostgreSQL FKs and desktop/mobile Admin UI status.
