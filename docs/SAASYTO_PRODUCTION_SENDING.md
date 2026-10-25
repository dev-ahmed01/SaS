# Sponsor a Salah — sending campaigns to real CRM contacts

## Scope

This is the **production** implementation for consented contacts who were
registered through the CRM, whether entered today or previously. There is no
seed-list dependency. A contact does **not** need an account with Saasyto:
only the Foundation's **sending** WhatsApp account is connected to Saasyto.

The single-phone `SAASYTO_LOCAL_TEST_PHONE` safeguard applies only to the
separately protected localhost demo. **Do not remove it or weaken the
development security gate to test broader sending.** Real multi-recipient
dispatch requires a production deployment, live PostgreSQL, a connected sender,
documented consents, and a continuously operating private worker.

## Backend production environment

Set these values in the **API backend's** secret environment (e.g. hosting
service's protected environment-variable panel), not in Next.js, public frontend
settings, a screenshot, Git, or an issue. Placeholders below are not real values.

```dotenv
APP_ENV=production
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://<db-user>:<db-password>@<db-host>:5432/<db-name>?sslmode=require
AUTH_SECRET=<new-long-random-secret-at-least-32-characters>
UPI_MATCH_SECRET=<new-independent-random-secret-at-least-32-characters>

SAASYTO_LOCAL_TEST_ENABLED=false
# The local-only SAASYTO_LOCAL_TEST_PHONE is not used in production.
SAASYTO_INSTANCE_ID=<instance-id-of-the-connected-foundation-sender>
SAASYTO_ACCESS_TOKEN=<rotated-private-access-token>
SAASYTO_RUNNER_SECRET=<independent-private-random-secret-at-least-32-characters>
SAASYTO_ENABLE_AFTER=<activation-cutoff-2026-10-26T10:00:00+05:30>
SAASYTO_SENDER_APPROVED=false
SAASYTO_DELIVERY_ENABLED=false
```

**Important:** `SAASYTO_ENABLE_AFTER` must be a real ISO 8601 offset-aware
datetime, not the angle-bracket example above. Campaigns created **before**
the cutoff are not eligible for sending (and cannot be retried as backlog).
Choose the cutoff immediately before creating your first reviewed, authorized
production campaign. Do not set it far in the past. Its purpose is to prevent
historical test drafts from sending accidentally.

`AUTH_SECRET` and `UPI_MATCH_SECRET` may already be configured for your
live deployment. **Do not rotate existing production secrets casually** without
a session/data migration plan; the placeholders explain initial provisioning.
Protect `DATABASE_URL`, bearer tokens and the runner secret.

The API requires TLS PostgreSQL and the latest migrations:

```sh
cd apps/api
python -m alembic upgrade head
```

Keep both sending switches **false** until: the Foundation has verified the
Saasyto sender connection and authorization, proof of recipient opt-ins and
opt-outs, a single explicit recipient test has arrived on WhatsApp, and the
private worker has been successfully tested against its empty/controlled
queue. After those gates, set:

```dotenv
SAASYTO_SENDER_APPROVED=true
SAASYTO_DELIVERY_ENABLED=true
```

Restart/redeploy the API after changing its environment. Do not run the local
demo and live multi-recipient production mode against the same database.

## Private worker: configure exactly one of these methods

The worker **does not** need the Saasyto instance ID or access token; those
remain on the API. It requires:

```dotenv
SAS_API_PUBLIC_ORIGIN=https://api.your-domain.example
SAASYTO_RUNNER_SECRET=<exact-same-private-runner-secret-used-on-api>
```

The origin must be your actual **HTTPS API** address, not the Next.js web URL,
without a path, slash, query, username or custom port. The worker calls
`POST /internal/saasyto/dispatch` with an authenticated private runner
header; it does not send messages from the browser.

**On a VPS with a supervisor**, use an always-on process:

```sh
python scripts/saasyto_tick.py --loop --interval-seconds 60
```

Configure your process supervisor/service manager to restart it on failure,
run only **one scheduled worker instance** by default, and keep its secret
environment inaccessible to the public. The script exits if the origin or
runner secret is missing/malformed. An individual failed tick is logged in
aggregate and the next tick checks the pending queue; claimed recipients
are never automatically retried.

**With a managed cron service** (e.g. Render Cron Job), schedule every minute
and use a single invocation:

```sh
python scripts/saasyto_tick.py
```

Do **not** use `--loop` with a cron scheduler. The API also enforces a
maximum of 10 queued recipient attempts per tick. Sending 500 recipients
takes multiple successful ticks, and arrival speed depends on the connected
provider, traffic, and recipient WhatsApp availability. Provider rate limits
and sender reputation restrictions remain external to the CRM. No guaranteed
delivery times are implied.

The worker never constructs recipient lists from environment variables. Each
approved campaign selects live CRM contacts and stores one durable,
organization-scoped recipient record per approval. Each message is claimed
before network submission, and consent/status/address/STOP is checked again
immediately before it is sent. Queued/claimed/accepted/unknown/rejected
statuses are visible to Admin.

## Admin workflow

1. In **Prospects**, register real sponsors with their WhatsApp/mobile number.
   New records start CRM-Inactive. Mark Active through the CRM if appropriate.
   Registration alone is not messaging permission.
2. Record actual WhatsApp opt-in via the prospect's Communication permissions,
   with its authorization source and reference. Keep opt-outs respected.
3. In **Communication → Compose**, select WhatsApp and the audience:
   **Active** for Active sponsors, or **All contacts** if the campaign should
   also include newly registered, not-yet-Active contacts who have opted in.
   The preview displays eligible counts computed from live CRM data.
4. Enter the message, choose **Review & send** or **Plan for later**, create
   the campaign, then **Check recipients**. Confirm eligible and excluded
   counts; approval cannot proceed if the actual eligible recipient
   identities changed since the latest review.
5. Click **Approve WhatsApp delivery** and confirm. This freezes the approved
   audience and queues it. For production sending, the private worker
   processes recipients at/after the scheduled time.
6. Watch **Campaign results**. Pending campaigns refresh automatically
   while open. Accepted by Saasyto means **gateway submission only**.
   Delivered/read cannot be claimed until an authenticated provider status
   callback contract and message-ID correlation have been verified.

Unverified or unknown attempts are **never** automatically resent; check the
sender dashboard and recipient device before creating any new campaign. To
stop pending sends, cancel the approved run or disable
`SAASYTO_DELIVERY_ENABLED` on the API and restart it. No submitted message
can be recalled by cancellation.

## Launch acceptance checklist

- Confirm the sending number is currently connected in the *authorized*
  Saasyto instance. An instance ID/token alone cannot prove connection.
- Verify a single documented-opt-in recipient and a separate explicit opt-out,
  using **real devices**, before considering a broader campaign.
- Confirm fresh registrations with opt-in appear in an **All contacts**
  preflight; confirm Inactive reminders and revoked consent are excluded.
- Prove one message arrived in the recipient's WhatsApp. Do not equate
  Saasyto's generic `status: success` with recipient delivery.
- Approve a small genuine audience and check worker submission, per-contact
  outcomes, pending cancellation, and scheduling in a controlled rollout.
- Ensure business messaging complies with applicable WhatsApp policy,
  especially opt-in, expected content, frequency, and opt-outs. A QR-linked
  third-party instance should not be assumed to be the official Cloud API.

**Deployment status:** This document and code prepare the production flow.
GitHub CI uses synthetic records and a fake provider: it cannot prove the
Foundation's connected Saasyto sender, live server configuration, or receipt
on actual WhatsApp. Do not advertise live delivery as complete until the
operational checks above pass.
