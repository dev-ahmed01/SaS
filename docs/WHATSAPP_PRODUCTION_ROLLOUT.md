# WhatsApp production rollout — individual OTPs and multi-recipient campaigns

## What is implemented

The Admin opens the **specific** registered prospect and clicks **Mark Active**.
This creates a random four-digit, two-minute challenge bound to that prospect,
the current WhatsApp number, and the organization. It submits a Meta
AUTHENTICATION copy-code template to that **one** number, never to all contacts.
Entering the correct OTP activates only that record. Resend cooldown is 60
seconds, at most five issues in 24 hours per recipient number, and five incorrect
attempts lock the challenge. Provider acceptance does not prove delivery.

This path uses `OTP_DELIVERY_ENABLED=true` and the `OTP_META_*` credentials.
It does **not** use `SAASYTO_LOCAL_TEST_PHONE` in production, and it does not
require `SAASYTO_DELIVERY_ENABLED` or the campaign runner.

Separately, the Communication Campaigns flow previews recipients, enforces
current opt-in and opt-out state, requires explicit Admin approval, and creates
one durable recipient queue entry per eligible phone. The production Saasyto
dispatcher can handle multiple recipients (up to 500 per approved campaign;
at most ten claims in a single runner tick). No blanket permission is inferred
from CRM Active status. A person who is both a Prospect and Promoter with
the same phone is de-duplicated within combined-audience campaigns. The
provider's message acceptance is recorded as *accepted_unverified*, not
automatically as delivered or read.

Production rollout is blocked until the Foundation owns/authorizes its
sending accounts and phone numbers, provider terms and recipient permissions
are verified, and the real credentials below are configured.

## 1. Meta authentication template setup

1. Open **Meta for Developers**: https://developers.facebook.com/apps/ and
   connect a Meta Business Portfolio and WhatsApp Business Account (WABA).
2. Register/verify the Foundation's WhatsApp sender. Obtain the **Phone Number
   ID** (numeric API ID, not the displayed phone number) from WhatsApp API Setup
   or the WABA phone-numbers endpoint:
   https://www.postman.com/meta/whatsapp-business-platform/request/hrio0ah/get-phone-number-id
3. Create an **AUTHENTICATION → Copy Code** template in WhatsApp Manager. Set
   the fixed optional expiration warning to **2 minutes**, approve its exact
   language, and copy the approved template's name.
   Template reference:
   https://www.postman.com/meta/whatsapp-business-platform/request/6vkv46u/create-authentication-template-w-otp-copy-code-button
4. In Meta Business Settings assign the WABA to an appropriately scoped system
   user and generate a server-side access token with
   `whatsapp_business_messaging` permission. For template management, access
   to `whatsapp_business_management` may also be required. Never share the
   token in chat, front-end configuration, screenshots, or source control.
5. Verify the WABA account's production permissions and that the selected
   template is approved. A Meta testing sender or temporary test access token
   is not sufficient for unrestricted outreach.

## 2. API production .env — copy and replace placeholders

Store **only** in `apps/api/.env` for a private deployment, or the hosting
provider's encrypted environment settings. Never commit live values.

```dotenv
APP_ENV=production
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=require
AUTH_SECRET=GENERATE_A_RANDOM_SECRET_OF_32_PLUS_CHARACTERS
UPI_MATCH_SECRET=YOUR_EXISTING_STABLE_UPI_MATCH_SECRET

# OTP to the *selected* registered prospect via Meta Cloud API
OTP_SECRET=GENERATE_A_DIFFERENT_RANDOM_SECRET_32_PLUS_CHARACTERS
OTP_LOCAL_PILOT_ENABLED=false
OTP_DELIVERY_ENABLED=true
OTP_META_ACCESS_TOKEN=YOUR_META_SYSTEM_USER_ACCESS_TOKEN
OTP_META_PHONE_NUMBER_ID=YOUR_NUMERIC_SENDER_PHONE_NUMBER_ID
OTP_META_TEMPLATE_NAME=YOUR_APPROVED_AUTHENTICATION_COPY_CODE_TEMPLATE
OTP_META_TEMPLATE_LANGUAGE=en_US
OTP_META_GRAPH_VERSION=v23.0

# The campaign sender is independent; leave off until Saasyto production is approved.
SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_DELIVERY_ENABLED=false
SAASYTO_SENDER_APPROVED=false
OTP_ACTIVATION_NOTICE_ENABLED=false

# Independent Pabbly/reminder system: off unless separately provisioned.
MESSAGING_DELIVERY_ENABLED=false
MESSAGING_SENDER_APPROVED=false
```

`OTP_META_GRAPH_VERSION` must match a currently supported Meta Graph API
version for the WABA. `OTP_META_TEMPLATE_LANGUAGE` must match the exact
approved language (e.g. `en` vs `en_US`). Retain your existing
`UPI_MATCH_SECRET`; rotating it will invalidate existing UPI digests.
Keep `OTP_SECRET` stable while OTP challenges are pending.
Database hosting must use valid PostgreSQL TLS and separately provisioned
Admin credentials; the localhost-only demo-login mode is not allowed in
production.

No `SAASYTO_LOCAL_TEST_PHONE` is needed or used for the production Meta OTP
path. Delete that line from production settings, rather than assigning one
sponsor's number to it.

## 3. Enable approved multi-recipient Saasyto campaigns

Only **after** validating the actual provider contract and that the sender
may legitimately send approved bulk WhatsApp messages to registered opted-in
recipients, change/add these values **on the production API host**:

```dotenv
SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_DELIVERY_ENABLED=true
SAASYTO_SENDER_APPROVED=true
SAASYTO_INSTANCE_ID=YOUR_OWN_VERIFIED_INSTANCE_ID
SAASYTO_ACCESS_TOKEN=YOUR_EXISTING_PRIVATE_ACCESS_TOKEN
SAASYTO_ENABLE_AFTER=YOUR_ACTUAL_APPROVED_GO_LIVE_TIME_WITH_TIMEZONE
SAASYTO_RUNNER_SECRET=DIFFERENT_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
# Optional individual post-activation confirmation, if separately authorized:
OTP_ACTIVATION_NOTICE_ENABLED=false
```

For instance, a future go-live instant could be written
`2026-11-01T09:00:00+05:30`, but **do not** blindly use an example date:
set the *actual agreed* sender activation instant. Only campaigns created
after this cutoff are eligible for approval; new campaigns need a fresh
recipient check and explicit approval. The local test-mode flag is **false**,
so the one-number local allowlist does not apply to production batches.

Deploy the independent private worker with these secrets as server-side
environment values (do not put the runner secret into web/public variables):

```dotenv
SAS_API_PUBLIC_ORIGIN=https://YOUR_REAL_API_HOST
SAASYTO_RUNNER_SECRET=THE_SAME_PRIVATE_RUNNER_SECRET_AS_API
```

Run `python scripts/saasyto_tick.py` from an approved scheduler/cron job.
It processes at most ten queued contacts per tick. The system commits a
claim before a provider request and never blindly retries an uncertain
outcome. This deliberately favors avoiding duplicate messages over
guaranteeing every provider submission.

**Do not run the localhost Saasyto pilot worker in production.**
The local mode (`APP_ENV=development`,
`LOCAL_DEMO_LOGIN_ENABLED=true`, `SAASYTO_LOCAL_TEST_ENABLED=true`,
`OTP_LOCAL_PILOT_ENABLED=true`) sends only to one allowlisted number.
It cannot be transformed into unrestricted sending by switching off just
one flag: development mode rejects Saasyto delivery without its pilot guard,
and official Meta OTP is restricted to approved production mode.

## 4. Verification and rollback

Before enabling any provider, run from `apps/api`:

```powershell
.\.venv\Scripts\python.exe -c "from app.config import get_settings; get_settings(); print('Configuration valid')"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

A configuration validation error is an intentional fail-closed signal.
Check the actual .env on the machine running the API; GitHub has no access
to local .env files. For a production deployment, set variables in the
hosting platform rather than changing the Windows localhost development
database to production mode.

Confirm with separate consented test prospects that:

- Clicking Mark Active for Person A requests an OTP **only to A**.
- Person B never receives A's code. A wrong, expired, replayed, or
  phone-changed challenge cannot activate anyone.
- A successful OTP activates only A; it does not create marketing permission.
- An approved three-person campaign creates independent recipient attempts,
  while a later STOP/opt-out suppresses that recipient.
- The system does not claim WhatsApp *delivered* or *read* unless a trustworthy
  correlated provider callback is later integrated.

**Emergency stop**: set `OTP_DELIVERY_ENABLED=false` to stop new OTPs,
and `SAASYTO_DELIVERY_ENABLED=false` to stop new campaign submissions,
then restart/redeploy the API and pause the scheduler. Previously accepted
external WhatsApp submissions cannot be recalled.

## 5. Credentials checklist

You must personally provision (or have the Foundation administrator provision)
the Meta Business account, registered sender Phone Number ID, Meta system
user token, approved authentication template and its exact language.
Separately, only enable Saasyto production dispatch after sender identity,
provider permissions, permitted message types, billing and actual delivery
are established. The source code cannot generate these credentials or
retroactively approve an account or template.
