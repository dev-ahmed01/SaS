# Two-number local Saasyto session — OTP + reminder

This session runs Next.js and FastAPI on your computer and sends approved WhatsApp
messages through your existing Saasyto account. Hosting is not required.

## Temporary database — no persisted sponsor test records

Use the separate docker-compose.saasyto-session.yml, which names its own
Compose project and mounts PostgreSQL data on tmpfs (RAM) rather than a
persistent volume. Docker Desktop must be running, and port 5432 must be free.
From the repository root in PowerShell:

    docker compose stop db
    docker compose -f docker-compose.saasyto-session.yml up -d

Stopping the *normal* db service preserves its existing volume and records.
Never run docker compose down -v on your original database. The session DB is
empty, so create a temporary Admin account after migrations. Use a matching
sas_dev database password in the Compose service and API DATABASE_URL.

Test data exists temporarily in the DB container's memory and disappears
when that container is removed. Browser session caches and messages stored
by Saasyto/WhatsApp may still exist. No cloud database is required.

## One local API .env for BOTH features

Save to apps/api/.env, keeping your existing private passwords/secrets (do
not put secrets in Git, chat, or frontend variables):

    APP_ENV=development
    LOCAL_DEMO_LOGIN_ENABLED=true
    DATABASE_URL=postgresql+psycopg://sas_dev:YOUR_TEMP_PASSWORD@127.0.0.1:5432/sas_dev
    SAASYTO_DELIVERY_ENABLED=true
    SAASYTO_SENDER_APPROVED=true
    SAASYTO_LOCAL_TEST_ENABLED=true
    SAASYTO_LOCAL_TEST_PHONE=+91FIRST_AUTHORIZED_WHATSAPP_NUMBER
    SAASYTO_LOCAL_TEST_PHONE_2=+91SECOND_AUTHORIZED_WHATSAPP_NUMBER
    SAASYTO_INSTANCE_ID=YOUR_EXISTING_INSTANCE
    SAASYTO_ACCESS_TOKEN=YOUR_EXISTING_ACCESS_TOKEN
    SAASYTO_RUNNER_SECRET=YOUR_EXISTING_PRIVATE_SECRET_AT_LEAST_32_CHARACTERS
    SAASYTO_ENABLE_AFTER=YOUR_AUTHORIZED_TIME_WITH_TIMEZONE_BEFORE_NEW_CAMPAIGNS
    OTP_LOCAL_PILOT_ENABLED=true
    OTP_SAASYTO_ENABLED=false
    OTP_DELIVERY_ENABLED=false
    OTP_ACTIVATION_NOTICE_ENABLED=false
    OTP_SECRET=YOUR_EXISTING_PRIVATE_OTP_SECRET_AT_LEAST_32_CHARACTERS
    MESSAGING_DELIVERY_ENABLED=false

Preserve AUTH_SECRET and UPI_MATCH_SECRET. Neither Meta API nor hosted data is
needed. Every outgoing local test WhatsApp number must match one of the
two separate, owner-authorized +countrycode mobile numbers exactly.
Third numbers cannot receive test OTPs or campaign messages.
The sender has to actually be connected in Saasyto; the owners of both
recipient numbers must have authorized messages. The cutoff must be before
the newly created campaign; generate the authorized local IST time with:

    (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')

## Start API and frontend

From apps/api in the API PowerShell window:

    .\.venv\Scripts\python.exe -c "from app.config import get_settings; get_settings(); print('Configuration valid')"
    .\.venv\Scripts\python.exe -m alembic upgrade head

The memory database starts empty. Set BOOTSTRAP_ADMIN_EMAIL and
BOOTSTRAP_ORGANIZATION in that terminal, then provision once:

    $env:BOOTSTRAP_ADMIN_EMAIL="pilot@example.org"
    $env:BOOTSTRAP_ORGANIZATION="Emlen Foundation - Test"
    .\.venv\Scripts\python.exe -m app.bootstrap_admin

Enter a new password when prompted; do not reuse a real Foundation login.
Start the API:

    .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001

In a different terminal, from apps/web (with API_INTERNAL_URL pointed to
http://127.0.0.1:8001 in the existing .env.local):

    npm run dev -- --port 3002

Open http://localhost:3002 and log in to the temporary Admin.

## One run, no settings switches

1. Register test Prospect A with the first authorized number and test
   Prospect B with the second. Record their actual WhatsApp opt-in at intake
   only if permission was granted. Do not fabricate consent.
2. Open A -> Mark Active. The API sends a unique four-digit OTP only to A's
   own registered WhatsApp number. Enter A's code within two minutes.
3. Repeat for B, using B's own OTP. Both should become CRM Active.
4. Open Communication -> Compose. Choose WhatsApp, Prospects, Active,
   category Reminder, and Review & send (not Plan for later).
   Message example: Test reminder for {{name}} — no payment requested.
5. Open Campaigns -> View results -> Check recipients and verify exactly
   two authorized, opted-in contacts are eligible. A third is not allowed.
6. Click Send WhatsApp now. Both individually addressed messages are
   submitted by the single Admin action; no separate worker is needed.
   Review the results per contact and verify actual receipt in WhatsApp.

Note: this tests a manually triggered Reminder-category WhatsApp campaign,
not the separate automatic 5th/20th reminder scheduler. Saasyto gateway
acceptance is not delivery or a read receipt.

## End the session and discard data

Stop the API with Ctrl+C, then run from repo root:

    docker compose -f docker-compose.saasyto-session.yml down

This removes the temporary PostgreSQL container and its memory-only test
records. Afterward, you may restore the normal persistent local database:

    docker compose start db

Messages already accepted by Saasyto cannot be recalled, and WhatsApp chat
history exists outside the temporary CRM database. Do not mix the original
persistent database with this disposable testing session.
