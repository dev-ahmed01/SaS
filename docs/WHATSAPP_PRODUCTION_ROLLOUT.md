# Sponsor a Salah — WhatsApp through Saasyto

The Foundation has chosen **Saasyto** as its WhatsApp sending provider. The
CRM does **not** require a separate Meta Cloud API token or direct Meta
pay-per-message integration when the approved Saasyto sender is used.

The external WhatsApp platform still has policies; Saasyto's subscription
pricing does not establish that all automated authentication or bulk messages
are authorized. Confirm this use with Saasyto and the Foundation's sender
owner before enabling live sends. Saasyto's personal-number offering links a
WhatsApp account and admits that blocking risk cannot be ruled out. If the
provider cannot support authorized OTP authentication, leave OTP sending
disabled rather than silently switching to an unrelated provider.

## Two distinct message workflows

1. **Prospect activation OTP**: Only an authenticated Admin clicking **Mark
   Active** for **one particular registered prospect** requests the OTP.
   The API looks up that person's `whatsapp_number` or `mobile_number`,
   creates a unique four-digit challenge (two minutes, maximum five guesses,
   one-minute resend cooldown, five issues/day per number), and passes that
   number and OTP only to `saasyto_client.send_text`. It never sends one
   person's OTP to all prospects, to the Admin, or to a hardcoded test number
   in production. Successful verification activates **only that prospect**.
   Provider acceptance does **not** mean delivered/read.
2. **Communication campaigns**: Admin selects eligible recipients, reviews
   consent exclusions, approves an audience, and the independent background
   scheduler submits an individual Saasyto request per eligible address.
   The queue supports multiple addresses: up to 500 per approved campaign
   and up to ten per worker tick. An opt-out suppresses that contact even
   after initial approval; a Prospect who is also a Promoter is de-duplicated
   by phone number.

An active CRM status alone is **not** permission for unsolicited WhatsApp
marketing messages. The existing one-time registration permission and current
opt-out history are reused; no redundant consent prompt appears on every
campaign. The prospect's affirmative request to verify their number or an
equivalent documented verification permission should be obtained before
triggering an OTP.

## Option A: Current Windows localhost one-number Saasyto pilot

Keep the local development database and its existing connection settings.
For `C:\Users\Admin\Desktop\SaS\apps\api\.env`, retain your private
instance/token/runner/OTP secret and configure:

```dotenv
APP_ENV=development
LOCAL_DEMO_LOGIN_ENABLED=true

SAASYTO_DELIVERY_ENABLED=true
SAASYTO_SENDER_APPROVED=true
SAASYTO_LOCAL_TEST_ENABLED=true
SAASYTO_LOCAL_TEST_PHONE=+91YOUR_AUTHORIZED_TEST_NUMBER
SAASYTO_ENABLE_AFTER=YOUR_EXISTING_TIMEZONE_AWARE_SENDER_ACTIVATION_TIME
SAASYTO_INSTANCE_ID=YOUR_EXISTING_INSTANCE
SAASYTO_ACCESS_TOKEN=YOUR_EXISTING_SAASYTO_ACCESS_TOKEN
SAASYTO_RUNNER_SECRET=YOUR_EXISTING_PRIVATE_RUNNER_SECRET_32_PLUS_CHARACTERS

OTP_LOCAL_PILOT_ENABLED=true
OTP_SAASYTO_ENABLED=false
OTP_DELIVERY_ENABLED=false
OTP_SECRET=YOUR_EXISTING_PRIVATE_OTP_SECRET_32_PLUS_CHARACTERS
OTP_ACTIVATION_NOTICE_ENABLED=true
```

The local demo-login safeguard only allows the loopback
`postgresql+psycopg://sas_dev:...@127.0.0.1:5432/sas_dev` development
database. No `OTP_META_*` keys are needed. The local pilot **will not**
send OTPs or campaigns to arbitrary prospect numbers. This restriction
prevents accidental testing on donors.

## Option B: Approved production Saasyto for actual registered numbers

Use these API-host environment settings **only after** the Foundation's
Saasyto sender and intended message types are approved. On a hosted
backend/VPS, store the secrets in the server's encrypted settings.
Do not commit `.env` and do not put credentials in frontend variables.

```dotenv
APP_ENV=production
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://DB_USER:DB_PASSWORD@DB_HOST:5432/DB_NAME?sslmode=require
AUTH_SECRET=YOUR_PRIVATE_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
UPI_MATCH_SECRET=YOUR_EXISTING_STABLE_UPI_MATCH_SECRET

# All WhatsApp sends use YOUR Saasyto instance.
SAASYTO_DELIVERY_ENABLED=true
SAASYTO_SENDER_APPROVED=true
SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_INSTANCE_ID=YOUR_VERIFIED_INSTANCE_ID
SAASYTO_ACCESS_TOKEN=YOUR_PRIVATE_SAASYTO_ACCESS_TOKEN
SAASYTO_RUNNER_SECRET=YOUR_PRIVATE_RANDOM_RUNNER_SECRET_AT_LEAST_32_CHARACTERS
SAASYTO_ENABLE_AFTER=YOUR_APPROVED_GO_LIVE_TIME_WITH_TIMEZONE

# Each admin-triggered OTP goes to the selected prospect.
OTP_SAASYTO_ENABLED=true
OTP_LOCAL_PILOT_ENABLED=false
OTP_DELIVERY_ENABLED=false
OTP_SECRET=YOUR_PRIVATE_RANDOM_OTP_SECRET_AT_LEAST_32_CHARACTERS
OTP_ACTIVATION_NOTICE_ENABLED=false

# Optional separate Pabbly/Meta transports remain off.
MESSAGING_DELIVERY_ENABLED=false
MESSAGING_SENDER_APPROVED=false
```

No `SAASYTO_LOCAL_TEST_PHONE`, `OTP_META_ACCESS_TOKEN`,
`OTP_META_PHONE_NUMBER_ID`, or Meta template is required on this
Saasyto-only route. Do **not** set `OTP_DELIVERY_ENABLED=true`;
that flag is for the *alternative* direct Meta adapter and must remain false.
`OTP_SAASYTO_ENABLED` is rejected unless the app is production, Saasyto
delivery/sender approval are true, and local pilot/Meta modes are off.
`OTP_SECRET` must be stable while challenges are pending. Keep the existing
`UPI_MATCH_SECRET`; rotating it breaks older UPI match digests.

The `SAASYTO_ENABLE_AFTER` cutoff must be an actual, timezone-aware date
and time approved for your sender, for example:
`2026-11-01T09:00:00+05:30` **only if that is your real go-live time**.
New campaigns created before this instant require new approval plans.
The setting is not a bypass for platform message restrictions.

### Worker for scheduled/bulk campaigns

Production **OTP requests send directly** to Saasyto when the Admin clicks
Mark Active. They do not require a campaign scheduler. For *campaigns*, run
the existing trusted private worker on an approved host. It uses separate
environment values:

```dotenv
SAS_API_PUBLIC_ORIGIN=https://YOUR_PRODUCTION_API_HOST
SAASYTO_RUNNER_SECRET=THE_SAME_SECRET_AS_THE_PRODUCTION_API
```

The scheduler executes:

```bash
python scripts/saasyto_tick.py
```

The worker processes at most ten eligible recipients per tick, applies
live opt-out checks, and never blindly retries uncertain submissions.

## Verification, rollout, and rollback

Run from `apps/api` before deploying (or use the server's venv):

```powershell
.\.venv\Scripts\python.exe -c "from app.config import get_settings; get_settings(); print('Configuration valid')"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

1. With authorized test prospects A and B, click **Mark Active** for A and
   verify only A's own WhatsApp receives the new code.
2. Confirm A's correct four-digit code activates A in less than two minutes;
   A's code must not activate B and cannot be replayed.
3. Trigger a separate OTP for B and confirm only B gets it.
4. Review/approve a small consented campaign; verify each eligible recipient
   is queued once and opted-out contacts are suppressed.
5. Check actual delivery manually: Saasyto API acceptance alone is **not**
   a WhatsApp delivered/read acknowledgement.

To stop new OTP issuance immediately, set `OTP_SAASYTO_ENABLED=false`
and restart/redeploy the API. To stop new campaign sends, also set
`SAASYTO_DELIVERY_ENABLED=false` and pause its worker. Previously accepted
provider requests cannot be recalled.

## Provider and platform limitations

Saasyto advertises personal-number/QR-linked sending with low subscription
pricing and zero per-message cost, but it does not promise that a number
cannot be blocked. Consult the product and relevant terms directly:
- https://saasyto.com/whatsapp-personal/
- https://whatsappbusiness.com/policy/

Ask Saasyto to confirm in writing that the account and API endpoint are
appropriate for **one-time authentication/activation codes** and
permission-based **bulk donor notifications** using this connected number.
The API's unverified acceptance response should not be represented in the
CRM as proof of delivery. All production secrets remain in the API host.
