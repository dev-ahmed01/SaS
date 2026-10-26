# Sponsor WhatsApp phone verification — implementation and provider handoff

> **Current Saasyto-first deployment (26 Oct 2026):** The Foundation uses
> Saasyto for WhatsApp, not a separately billed direct Meta API integration.
> See [WhatsApp Production Rollout](WHATSAPP_PRODUCTION_ROLLOUT.md) for the
> current `OTP_SAASYTO_ENABLED=true` production configuration, which sends
> OTPs to each selected prospect's own registered number through Saasyto.
> The previous Meta-only and single-number Saasyto statements below record
> the initial implementation and are **not current deployment instructions**.


## Status (24 October 2026)

**OTP-gated activation is implemented; outbound OTP delivery remains OFF by default until an approved provider is configured.**

The supplier named in the meeting as **“Sassito”** (also described as **“Sassy WA”**) has not been conclusively identified. Two separate public products were found: [Saasyto](https://saasyto.com/) and [Sassy Infotech](https://www.sassyinfotech.com/). Do **not** assume they are the same company, treat Saasyto's QR-linked personal-number automation as an official OTP sender, or enter unknown vendor credentials into a Meta API setting.

A documented **direct Meta WhatsApp Cloud API** transport has been prepared as an independent option. Saasyto claims API/webhook capability but its public pages do not supply a verified sponsor-OTP endpoint/authentication contract.

## What works in the code

- Admin-only **Prospect Details → Mark Active** OTP challenge and verification. First activation requires only a fresh four-digit OTP; reactivation after a previous active period requires both an explanatory note and a NEW OTP.
- Direct calls to the generic `/stage` endpoint cannot activate a prospect, even if the number had been verified previously. The `/otp/activate` endpoint consumes an unexpired challenge and records activation atomically.
- Six-digit server-generated random challenge, ten-minute expiry, 60-second resend cooldown and five requests per 24 hours per prospect. Five incorrect attempts lock a challenge.
- Database-backed, tenant- and prospect-bound challenge and current-phone HMAC digest. OTP plaintext is never stored, logged, added to audit logs or returned to browsers.
- Explicit CSRF on request and verification; challenge IDs never function as proof without the OTP.
- One-time successful verification and audited time; editing the phone/WhatsApp number revokes verified state, and old challenges are refused.
- The standalone phone-verification endpoint is separate from CRM stage; only `/otp/activate` changes CRM stage. Financial lifecycle/payment status remains separate. OTP never overrides an opt-out or invents communication consent.
- Prospect registration provides a one-time, explicit Admin attestation checkbox for the sponsor's WhatsApp reminders/updates permission. The backend records its evidence reference in the existing consent ledger; an opted-in, activated sponsor does not need a second consent entry.
- Meta send call uses a preapproved WhatsApp **AUTHENTICATION** copy-code template with identical OTP in body and button. A valid Meta message ID means only **accepted by provider**, not delivered/read.
- No queued or historical OTP replay; disabled configurations return HTTP 503 before a challenge is issued.
- Schema migration: `0019_sponsor_otp`. Applying this migration is required before deploying the new API.

## Minimal setup for the Foundation (direct Meta path)

1. Own/control the sender's WhatsApp Business Account (WABA), Meta Business Portfolio and linked phone. Confirm this is the actual agreed sender; **do not** replace the contracted Sassy provider without approval.
2. In Meta WhatsApp Manager, create and obtain approval for an **AUTHENTICATION → Copy Code** template (for example a vendor-approved template named `sponsor_verify_code`). Confirm approved language code. This is NOT a generic marketing, reminder or utility template.
3. Store these secrets/config values *only on the API host* (Render secret environment variables or trusted equivalent). Do not commit them, paste the token into chat or set `NEXT_PUBLIC_*`:
   - `OTP_SECRET` — stable random 32+ character secret, different from `AUTH_SECRET` and messaging webhook secrets
   - `OTP_META_ACCESS_TOKEN` — restricted Meta system-user access token authorized for WhatsApp messaging
   - `OTP_META_PHONE_NUMBER_ID` — numeric registered sender phone-number ID
   - `OTP_META_TEMPLATE_NAME` — exact approved lowercase template name
   - `OTP_META_TEMPLATE_LANGUAGE` — exact approved language (default `en_US`)
   - `OTP_META_GRAPH_VERSION` — supported/pinned Graph version (default in example `v23.0`)
4. Apply Alembic migrations (`alembic upgrade head`) on the backend, verify the sender, template, number ownership, costs and opt-in/notification handling, and only then set `OTP_DELIVERY_ENABLED=true` in **production**. This flag is independent of `MESSAGING_DELIVERY_ENABLED`, Saasyto direct messaging and Pabbly. Enabling OTP does not turn on reminders. Local Saasyto pilot credentials alone do NOT enable the official Meta OTP path.
5. In a controlled test, register a **test** prospect with the sponsor's documented WhatsApp permission (if granted). Open Prospect Details → Mark Active (sends OTP automatically) → enter the received four digits → Verify OTP & Activate. Mark the person inactive, then repeat and verify that a reactivation reason and a newly issued OTP are both mandatory. Change the phone and confirm verification resets.

Until the flag and all fields are validated the UI intentionally says the provider is not connected and cannot send. Development/staging modes refuse enabled *Meta* OTP delivery; tests inject a fake delivery adapter.

### One-number localhost OTP pilot with Saasyto

The existing localhost Saasyto setup may be used to test OTP delivery ONLY to the single authorized `SAASYTO_LOCAL_TEST_PHONE`. This is free-text OTP for developer testing, **not** an approved production authentication template or proof of delivered messages. Set the following in the existing `apps/api/.env`, without changing the sender instance/access token:

```dotenv
SAASYTO_LOCAL_TEST_ENABLED=true
SAASYTO_LOCAL_TEST_PHONE=+91YOUR_AUTHORIZED_NUMBER
SAASYTO_SENDER_APPROVED=true
SAASYTO_DELIVERY_ENABLED=true
OTP_LOCAL_PILOT_ENABLED=true
OTP_SECRET=YOUR_DIFFERENT_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
OTP_DELIVERY_ENABLED=false
```

Preserve the existing Saasyto credentials, runner secret and timezone-aware enable-after cutoff. Restart the API. The pilot refuses a non-allowlisted number, public/staging/production mode, absent authorization, or a missing OTP secret. The OTP code is never returned by the API. The sponsor must actually receive it on their own WhatsApp to activate. Turning on this local pilot does not enable production Meta OTP.

## If the agreed supplier is Saasyto or Sassy Infotech

Require the actual vendor's **product link and API PDF/Postman collection** (not screenshots or a generic marketing page), which shows:

- Authorized HTTPS send endpoint, authentication mechanism and scope, exact request/response contract, acceptance status and idempotency behavior.
- Whether the vendor has an **official Meta WhatsApp Business Platform** sender and can deliver approved AUTHENTICATION OTP templates with copy-code button to new contacts, rather than personal WhatsApp Web/QR-rotation or virtual numbers.
- Whose WABA and number the Foundation owns, linked sender ID, test environment and safe sandbox phone, quoted India authentication-message costs.
- Delivery webhook semantics, cryptographic signature verification, event IDs, retry/timeouts, data retention and deletion policy.
- If the vendor generates and verifies OTP itself, the **verify/check API** and challenge-ID binding contract rather than a code-delivery-only endpoint.

Once provided, the remaining work is implementing an approved adapter behind the current `_deliver` function (or a vendor-verified challenge adapter if OTP is provider-owned), configuring its credentials securely and confirming a genuine test send. **No vendor-specific endpoints have been invented.**

## Safety boundaries

- No OTP message is sent unless an authorized Admin clicks Mark Active (which initiates a single OTP request) or explicitly requests a replacement after expiry. Provider configuration is validated. The Saasyto path works only for the configured single authorized local number.
- The four-digit code expires after two minutes according to server time. Only the current accepted challenge is valid. Codes are randomly generated, do not repeat for a recent number's challenges, and are bound to the prospect and current WhatsApp phone. The OTP is not returned in the browser response. The UI displays four digit fields, the full number, and a countdown. Reopening the dialog within the validity window resumes the same challenge without sending again.
- OTP is not proof of payment, communication consent, or delivered messages. Only a successful activation challenge changes the CRM stage; financial sponsorship status remains payment-derived.
- Request submission is never echoed as a delivered notification. HTTP send response success only indicates provider acceptance.
- No blind provider retry after a timeout. Confirmation can be uncertain; operation reports that uncertainty.
- CI uses fake provider delivery and synthetic numbers, not live donor data.
- Authentication template docs: [Meta developer hub](https://whatsappbusiness.com/developers/developer-hub/), [Meta Cloud API](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started), [AWS reference payload](https://aws.amazon.com/blogs/messaging-and-targeting/send-whatsapp-business-messages-with-aws-end-user-messaging-social/).


## Activation acknowledgement after OTP (optional)

The application can submit a separate WhatsApp confirmation **after** the
atomic OTP activation succeeds, using the existing Saasyto account. Set
`OTP_ACTIVATION_NOTICE_ENABLED=true` only with an approved enabled Saasyto
sender and either the Meta OTP sender or the single-number localhost OTP pilot.
This flag defaults to false. The old Pabbly and reminder flags do not apply.

The confirmation is a registration/CRM status acknowledgement, **not**
an OTP, proof of payment, or a delivery receipt. The server checks the latest
documented general WhatsApp consent, any opt-out/STOP on a shared number,
the sender's timezone-aware enable-after cutoff and local allowlist. It sends
at most once for each successful OTP activation. Rejected/unknown provider
responses never roll back an activated sponsor and are **not retried**.

One-number local proof-of-concept uses the working
`SAASYTO_LOCAL_TEST_PHONE` alongside `OTP_LOCAL_PILOT_ENABLED=true`,
`OTP_SECRET` and the approved `SAASYTO_*` credentials; keep
`OTP_DELIVERY_ENABLED=false` there. Production OTP uses the separately
approved Meta authentication template.

No separate communication permission popup appears at activation. The intake
checkbox is an explicit Admin attestation of existing permission and is
recorded once in the communication consent ledger; a prior opt-out takes
precedence. Without existing evidence, activation still succeeds, but the
confirmation and later campaigns are suppressed.

### CRM administrator and phone visibility

The current authenticated CRM is designed around one Admin role, not a multi-role permission system. Prospect and campaign views remain Admin-authenticated. In campaign recipient details and local pilot readiness, the complete WhatsApp number is displayed rather than hiding its first digits. These pages must remain inaccessible to public/unauthenticated visitors.

Campaign sending history, consent attestations and financial transaction records are not purged as part of OTP updates. Historical campaign records need a separately approved deletion scope and retain audit obligations; never assume a vague request to clear campaigns authorizes deleting all related records.
