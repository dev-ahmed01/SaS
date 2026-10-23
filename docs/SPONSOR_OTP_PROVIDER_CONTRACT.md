# Sponsor OTP provider contract — pending verified Sassito integration

**Status:** Provider API contract unverified. No WhatsApp/SMS OTP is sent or claimed as verified by this change.

## Scope
New sponsor phone verification must be separate from CRM Active/Inactive, documented contact consent, and the financial lifecycle. Verifying possession of a phone number is **not** confirmation of communication opt-in or payment, and must never activate a sponsor automatically.

## Provider information needed before enabling the adapter
1. Confirm the exact vendor and product name referred to as "Sassito" in the 22 October 2026 meeting, and a vendor-authorized HTTPS API base URL.
2. Supply official send/check API reference (HTTP methods, paths, authentication headers and scopes, request/response fields, error codes, sandbox mode, test examples). Never store keys in source control or chats.
3. Confirm whether OTP is vendor-generated/verified or locally generated with vendor delivery only; these have different storage and verification contracts.
4. Confirm the approved WhatsApp **AUTHENTICATION** template and template ID, linked sending number, and ability to send to uninitiated numbers; include delivery callbacks or status checking.
5. Provide nonproduction restricted credentials in hosting secrets, webhook signing/verifying details, allowed IPs and rate limits, and provider cost/throughput limits.
6. Specify intended sponsor UX (admin-created record vs self-registration), number-change rules, resends and contact-number re-verification policy.

## Required security behavior
- Use the configured provider only through a server-side adapter, never from the browser or a query parameter.
- Server-bound challenges must carry organization, sponsor, intended mobile number and creation time; expire quickly (e.g. ten minutes), allow bounded attempts (e.g. five), and apply per-number/IP cooldown plus quotas.
- Store only salted/peppered verification data or opaque provider challenge IDs, never plaintext OTP in database, logs, audit events, URLs or analytics.
- Return nonenumerating responses when requesting OTP, and enforce CSRF and authorization at Admin endpoints.
- Require an approved provider result tied to the exact challenge and phone, not merely a successful HTTP response; update phone-verified status atomically and audit it.
- Fail closed on missing configuration, provider timeouts, invalid signatures or quota breaches. Do not mutate sponsor status on failures.
- Use a sandbox adapter for tests: successful verification, wrong/expired code, replay, wrong tenant, wrong phone, retry limit, webhook forgery, and provider error.
- Do not send real messages in CI or preview and never repurpose payment or reminder templates as OTP authentication templates.

## Release gate
The current CRM review leaves OTP sending/verification **disabled** until the real provider's documented endpoints and secret setup are verified. Existing WhatsApp consent and reminder transport controls remain separate and unchanged.
