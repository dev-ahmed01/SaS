# Saasyto campaign integration — verified surface and safe connector foundation

## Controlled localhost one-phone pilot (October 2026)

[Local CRM-only Saasyto setup](SAASYTO_LOCAL_CRM_PILOT.md) documents an opt-in
single-allowlisted-phone test while the API and database remain on Windows.
The local worker calls an authenticated loopback endpoint, not a Render job.
This mode requires `APP_ENV=development`, the exact safeguarded local-demo
PostgreSQL database, `SAASYTO_LOCAL_TEST_ENABLED=true`, and
`SAASYTO_LOCAL_TEST_PHONE=+countrycode...` (a documented opt-in recipient).
All normal sender approvals, fresh campaign checks, activation cutoffs,
and explicit approval are still required. Production behavior is unchanged.
It is **not** permission to send to other CRM contacts or to automate monthly
reminders. Never put API credentials or the private runner secret in frontend
settings.


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

- Independent `SAASYTO_*` config, off by default. In staging and ordinary development
  `SAASYTO_DELIVERY_ENABLED=true` is invalid; production requires both the
  sender approval flag and valid credentials. A separate one-phone localhost
  pilot is documented above. Separate from Pabbly reminder
  transport and Meta Cloud API OTP.
- `app.saasyto_client.send_text()`: fixed HTTPS host/path, documented JSON,
  5-second timeout, no redirects or environment-proxy trust, E.164 validation,
  no blind retry, and only `accepted_unverified`, `rejected` or `unknown`.
  The explicitly approved campaign dispatch worker is now wired to this
  transport; it remains off by default.
- `GET /v1/communication/provider/saasyto`: admin-authenticated, read-only
  configuration and verification status; never returns token or donor data.
- Next.js authenticated same-origin read-only gateway and Campaigns status
  text. The campaign approval button is shown only when backend configuration enables
  sending. In local pilot mode it permits one consented allowlisted phone.
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
4. **Campaign dispatch implementation:** A durable tenant-bound campaign queue,
   recipient opt-out recheck, Admin approval and bounded no-retry worker are
   implemented. Provider-message correlation and cryptographically authenticated
   callback reconciliation remain unverified.
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


## Additional provider documentation confirmed from the authenticated portal

The Saasyto Developer API **Reference → Success Response** shows a generic
JSON envelope:

```json
{"status":"success","message":"Action completed successfully","data":{}}
```

This is not a send-specific receipt: no stable message ID or delivery event
correlation has been verified. The portal also documents a separate
`POST https://web.saasyto.com/api/sendtemplate` endpoint and a
`POST /api/drip_enroll` for a **pre-existing drip sequence**. Neither is
proof of an API for creating new bulk campaigns.

The current account selector lists multiple sender instances, but the API
page does not establish their connection or WhatsApp platform compliance.
No instance is selected or changed by the integration. The documented
`/api/set_webhook` route is for receiving connection, incoming and outgoing
events, but the portal does not show a verifiable cryptographic signature
or delivery-correlation schema. Consequently SaS does not accept webhook
events as delivery proof yet.

## Campaign approval, durable delivery and reporting (PR #46)

The SaS Communication screen now supports *explicit* manual approval after a recipient
check completed within the preceding 15 minutes. It does not send on campaign
creation or immediately when a browser opens. A successful approval stores a
one-time tenant-bound run and immutable recipient identities. Per-recipient
consent, opt-outs, active state, segment and phone are recalculated at execution.

For first launch keep `SAASYTO_DELIVERY_ENABLED=false`. The approved
campaign button is hidden while disabled. It becomes available **only** when
the backend environment is configured, after prior security checks.

### Environment variables (API/server only)

```text
SAASYTO_DELIVERY_ENABLED=false
SAASYTO_SENDER_APPROVED=false
SAASYTO_INSTANCE_ID=<your account's sender instance ID>
SAASYTO_ACCESS_TOKEN=<rotated and newly generated private token>
SAASYTO_ENABLE_AFTER=<ISO-8601 datetime with offset, future relative to onboarding>
SAASYTO_RUNNER_SECRET=<unique 32+ character random private secret>
```

- Generate the runner secret separately from the Saasyto token. Never put
  secrets in frontend `NEXT_PUBLIC_*`, GitHub, shared screenshots or messages.
- Enabling is blocked outside approved production/test, or without approved sender,
  activation cutoff, runner secret and credentials.
- Only campaigns *created after* `SAASYTO_ENABLE_AFTER` are dispatch-eligible.
  This permanently prevents replay of historical campaigns and old demo records.
- Run `alembic upgrade head` to apply `0020_saasyto_campaigns`
  before deploying the new backend. Existing sponsor and campaign data is preserved.

### Queue worker

Only a trusted cron/worker may invoke this authenticated internal endpoint:

```http
POST /internal/saasyto/dispatch
X-Saasyto-Runner-Token: <private runner secret>
```

The worker handles at most ten queued recipients per invocation, in IST-scheduled
order. Suggested cadence: every minute via a privately configured Render Cron
Job or equivalent.
A runnable private tick is included: `python scripts/saasyto_tick.py`.
Configure the cron job with `SAS_API_PUBLIC_ORIGIN=https://YOUR-API-HOST`
(no path) and the same `SAASYTO_RUNNER_SECRET` as the API. The job will
refuse non-HTTPS endpoints, follows no redirects and emits aggregate counts only. **A scheduled job must be configured and tested before
promising unattended scheduled delivery.** The endpoint is safe to run against
an empty or disabled queue. It returns aggregate attempt counts only.

At each attempt the worker commits an irreversible `claimed` state *before*
network I/O. Worker crashes and uncertain timeouts leave that contact
`claimed`/`unknown`; neither is automatically retried. This favors
no accidental duplicate WhatsApp messages over guaranteed delivery.

### Current reporting limits

The app can truthfully report queued, claimed, accepted by provider gateway,
rejected, unknown and excluded. It **cannot** claim sent/delivered/read.
The screenshots show `set_webhook` with a query-parameter token. That does not
document a signed callback payload or event/message ID correlation. No inbound
webhook is allowed to change donor or campaign records until authenticity,
schema and matching fields are proven with a controlled provider fixture.

### Controlled acceptance before enabling

1. Rotate the potentially exposed example access token. Confirm your Saasyto
   sender is authorized and opt-ins are documented.
2. Confirm the generic documented success envelope with *one redacted*, real
   `POST /api/send` response (success and failure), the stable message ID, whether
   calls are idempotent, and the connected sender type.
3. Ask for one redacted sent/delivered/failed webhook event plus sender
   authentication or signature specification, webhook retries, and message ID
   correlation. Do not configure a webhook URL to a real SaS endpoint until
   verified. If Saasyto does not offer cryptographic signing, use a separate
   unguessable secret via a supported header and a locked-down ingress; never
   treat unsigned events as proof of delivery.
4. Use a test sponsor and a permitted test WhatsApp number to validate a
   single send and manually reconcile the provider dashboard. Only then
   set the enable switch and install the private cron.

**Separate concern:** The existing Meta Cloud API OTP implementation is *not*
wired to Saasyto's QR-instance API. OTP templates require their own approved
business sender and should not be treated as ordinary promotional text.
