# Saasyto campaign integration — verified surface and safe connector foundation

## Evidence verified from account screenshots, 24 October 2026

The Foundation's `web.saasyto.com` Developer API page shows:

- **Send Text:** `POST https://web.saasyto.com/api/send` with JSON body
  `number` (country-code digits), `type: "text"`, `message`, `instance_id`,
  and `access_token`.
- **Credentials:** instance ID and access token supplied in the account's API UI.
- **Set Webhook:** `/api/set_webhook` accepts
  `webhook_url`, `enable`, `instance_id`, and `access_token` in query
  parameters. **Do not invoke it yet:** endpoint uses URL query credentials
  and the event signature, event schema, retry policy, and test callback are
  not yet documented.
- Bulk-campaign UI is present, but no API contract for creating native bulk
  campaigns has been verified. SaS will therefore eventually submit one text
  per independently consented recipient, not fabricate a bulk endpoint.

Screenshots were *reference material*, not a live-send authorization. The
instance/token values appearing in them were **never added to the repository**.
If genuine, **rotate that exposed token**. Store new credentials only in
backend-secret settings.

## Implemented now

- Independent `SAASYTO_*` config, off by default. In staging/development
  `SAASYTO_DELIVERY_ENABLED=true` is invalid; production requires both the
  sender approval flag and valid credentials. Separate from Pabbly reminder
  transport and Meta Cloud API OTP.
- `app.saasyto_client.send_text()`: fixed HTTPS host/path, documented JSON,
  5-second timeout, no redirects or environment-proxy trust, E.164 validation,
  no blind retry, and only `accepted_unverified`, `rejected` or `unknown`.
  No caller invokes this transport from campaigns yet.
- `GET /v1/communication/provider/saasyto`: admin-authenticated, read-only
  configuration and verification status; never returns token or donor data.
- Next.js authenticated same-origin read-only gateway and Campaigns status
  text. The button to send is not exposed because genuine recipient-approval
  and provider-response verification have not been completed.
- Offline synthetic tests for request JSON, failure behavior, no retries,
  safety gating and status. No tests use real recipients or provider secrets.

## To complete end-to-end campaigns

1. **Saasyto account:** Confirm a connected sender in the account selector,
   and confirm whether it is a QR-linked personal WhatsApp instance versus an
   official Meta Business Platform sender. Use only an authorized,
   platform-compliant business messaging setup, with documented opt-in and
   opt-out procedures. The presence of a QR code does *not* demonstrate an
   official Meta API integration.
2. **Response contract:** Capture one *redacted* JSON response for a single,
   explicitly authorized test message. Need success/error fields and durable
   provider message ID, if available. Never show real token, personal mobile
   or identifiable recipient data.
3. **Webhook contract:** Obtain an example JSON status/delivery event,
   event names, signature or shared-secret validation mechanism and
   idempotency/replay semantics. Without authenticated receipts, only report
   submitted to provider/unknown—not delivered or read.
4. **Campaign dispatch implementation:** Add tenant-scoped per-recipient
   durable outbox, one-send-only keys, re-check permissions and unsubscribe
   immediately before each send, admin approval, bounded workers, explicit
   scheduled/now behavior, time-zone handling, report counts, and safe
   reconciliation for ambiguous timeouts. Keep no blind retries.
5. **Provision secrets:** Rotate any shown access token, then set
   `SAASYTO_INSTANCE_ID`, `SAASYTO_ACCESS_TOKEN`,
   `SAASYTO_SENDER_APPROVED=true`, and finally
   `SAASYTO_DELIVERY_ENABLED=true` **only in approved production**, once
   validation and reviewed onboarding are complete. Never place these in
   `NEXT_PUBLIC_*` or commit them to Git.
6. **Smoke:** Consent-gated, owner-authorized test number first. Confirm
   receipt, failure and opt-out. Keep production campaign sending disabled
   until this is verified.

## Important distinctions

- Saasyto's HTTP 2xx is *not* a WhatsApp delivery receipt.
- Pabbly monthly reminders and Meta Cloud OTP remain separate integrations.
- Older campaigns are saved plans; do not replay historical campaigns or
  send queued backlog automatically upon activation.
- The Send Text API is **not** proof of bulk-campaign creation APIs, template
  approval or webhook reliability.
- Saasyto markets an existing-personal-number messaging product; review
  WhatsApp's terms and consent restrictions before launching automated sends.
