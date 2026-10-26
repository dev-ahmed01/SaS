# Dynamic Saasyto localhost workflow — no recipient numbers in .env

The Admin can test real Saasyto OTP requests for **any registered prospect**
and then send a separate Reminder-category WhatsApp campaign to all
**eligible Active, opted-in** CRM recipients, without configuring or swapping
the recipients in the environment. This is an opt-in, guarded localhost
rehearsal, NOT automatic production approval or a blanket opt-in.

## How it works

- **OTP:** The authenticated Admin selects one Prospect -> Mark Active. The
  backend looks up that exact prospect's saved WhatsApp/mobile number,
  generates a random four-digit code bound to that prospect and number
  (two-minute expiry, attempt limits and resend cooldown), and submits ONE
  text to Saasyto. Only a valid code changes that prospect to Active.
- **Reminder:** Communication -> Compose -> WhatsApp -> Prospects -> Active
  -> Reminder -> Review & send. A fresh recipient check evaluates actual
  Active status, consent evidence, address duplication, and opt-outs. The
  Admin explicitly approves the current recipient list, then the **Send
  WhatsApp now** action submits at most one message per eligible approved
  recipient without any phone variables in .env. Sending rechecks opt-outs,
  Active status, and addresses. A campaign supports at most 500 recipients
  per approval, and a completed/unknown attempt is never blindly retried.
- The default deny-all sending mode remains unchanged. This new explicit
  setting requires APP_ENV=development, LOCAL_DEMO_LOGIN_ENABLED=true and
  the existing protected 127.0.0.1:5432/sas_dev connection.
- A Saasyto gateway acknowledgement is **not** proof the recipient received
  or read the WhatsApp. Confirm actual receipt separately.

## Optional: no persistent sponsor records on the computer

Use the previously supplied `docker-compose.saasyto-session.yml` when testing
without keeping test records between sessions. It uses a dedicated Compose
project and PostgreSQL data stored in tmpfs memory, not a persistent volume.

From `C:\Users\Admin\Desktop\SaS`:

```powershell
git switch main
git pull --ff-only origin main
# Only if the current normal Compose database is using port 5432:
docker compose stop db
# A dedicated temporary DB on 127.0.0.1:5432
docker compose -f docker-compose.saasyto-session.yml up -d
```

If `SAS_LOCAL_DB_PASSWORD` is set for the container, use the exact same
password in your local `DATABASE_URL` (otherwise the Compose default is
`change-me-for-local-only`). The temporary DB is empty; a test Admin must
be provisioned after migrations. Do not run `docker compose down -v`
against the original CRM: that could destroy existing data.

## One API .env, no phone numbers

Edit `apps/api/.env`. Keep existing private secrets and the verified
Saasyto credentials; do NOT add `SAASYTO_LOCAL_TEST_PHONE` or
`SAASYTO_LOCAL_TEST_PHONE_2`. Remove/comment any old copies of those
two lines. Replace `YOUR_...` placeholders with your private real settings.

```dotenv
APP_ENV=development
LOCAL_DEMO_LOGIN_ENABLED=true
DATABASE_URL=postgresql+psycopg://sas_dev:YOUR_TEMP_DB_PASSWORD@127.0.0.1:5432/sas_dev
AUTH_SECRET=YOUR_EXISTING_SECURE_AUTH_SECRET
UPI_MATCH_SECRET=YOUR_EXISTING_SECURE_UPI_MATCH_SECRET

# One explicitly enabled protected local dynamic mode, both features at once.
SAASYTO_LOCAL_DYNAMIC_ENABLED=true
SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_DELIVERY_ENABLED=true
SAASYTO_SENDER_APPROVED=true
SAASYTO_INSTANCE_ID=YOUR_EXISTING_SAASYTO_INSTANCE_ID
SAASYTO_ACCESS_TOKEN=YOUR_EXISTING_PRIVATE_SAASYTO_ACCESS_TOKEN
SAASYTO_RUNNER_SECRET=YOUR_PRIVATE_SECRET_AT_LEAST_32_CHARACTERS
SAASYTO_ENABLE_AFTER=YOUR_ACTUAL_APPROVED_CUTOFF_WITH_TIMEZONE

OTP_SAASYTO_ENABLED=true
OTP_LOCAL_PILOT_ENABLED=false
OTP_DELIVERY_ENABLED=false
OTP_SECRET=YOUR_EXISTING_PRIVATE_SECRET_AT_LEAST_32_CHARACTERS
OTP_ACTIVATION_NOTICE_ENABLED=false

MESSAGING_DELIVERY_ENABLED=false
```

`SAASYTO_ENABLE_AFTER` must be timezone-aware and earlier than the
creation time of a NEW reminder campaign. Use an actual agreed activation
instant, not an arbitrary past date to circumvent sender authorization.
`SAASYTO_SENDER_APPROVED=true` means that the sender owner authorized
both the one-to-one OTP and consented reminder use. The recipient also
needs to agree to receive the relevant messages, with evidence for
campaign opt-in. Do not mark everyone as opted in by default.

Note: No Meta Cloud API token/template is needed; `OTP_DELIVERY_ENABLED`
(the separate Meta option) remains false.

## Start on existing localhost ports

Stop the old API before changing .env. From `apps/api`:

```powershell
.\.venv\Scripts\python.exe -c "from app.config import get_settings; get_settings(); print('Configuration valid')"
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The disposable database is empty. To create a temporary Admin once:

```powershell
$env:BOOTSTRAP_ADMIN_EMAIL="pilot@example.org"
$env:BOOTSTRAP_ORGANIZATION="Emlen Foundation - Test"
.\.venv\Scripts\python.exe -m app.bootstrap_admin
```

Then start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

In the frontend terminal, ensure the existing `apps/web/.env.local`
contains `API_INTERNAL_URL=http://127.0.0.1:8001`, then:

```powershell
cd C:\Users\Admin\Desktop\SaS\apps\web
npm run dev -- --port 3002
```

Open `http://localhost:3002`; register your two test prospects with
different WhatsApp numbers. Test first person's Mark Active/OTP/verification,
then second person's. Record their valid WhatsApp reminder consent. Under
Communication -> Compose, create an unscheduled WhatsApp Reminder for
Active Prospects, click Check recipients, verify the actual eligibility list,
and click Send WhatsApp now. A third eligible recipient would also be included
if they had authorized the reminder; this is a **CRM-driven** workflow,
not a two-number allowlist.

**This tests manual reminder dispatch, not automatic 5th/20th calendar
scheduling.** The latter still needs its own worker/scheduler setup.

## End the isolated session

Stop the API and frontend, then from the repository root:

```powershell
docker compose -f docker-compose.saasyto-session.yml down
# Optional: restore the original persistent local DB
docker compose start db
```

The temporary test records, including OTP challenge hashes, vanish with
the removed tmpfs database container. This does NOT delete any external
Saasyto or WhatsApp chat history or local browser cache, and messages
already submitted cannot be recalled.

To stop future sending immediately, turn
`SAASYTO_DELIVERY_ENABLED=false` and restart the API. This mode should be
used only with an authorized sender and genuinely consented recipients.
