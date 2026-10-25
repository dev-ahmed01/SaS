# Saasyto WhatsApp — guarded localhost pilot

This setup allows a **single explicitly allowlisted and consented test phone** to
receive a WhatsApp campaign approved in Sponsor a Salah's local CRM. It is not
a general production sending switch or a replacement for official WhatsApp
sender compliance. This path is off by default.

## Preconditions

- Windows localhost Sponsor a Salah, using the isolated local-demo Admin,
  `APP_ENV=development`, `LOCAL_DEMO_LOGIN_ENABLED=true` and the existing
  `sas_dev` PostgreSQL database on `127.0.0.1:5432` with username `sas_dev`.
  Local pilot enablement is rejected on every other database/environment.
- Saasyto account has a connected, authorized instance with current private
  credentials. Do **not** share your real token in chat or commit it to Git.
- One *real*, explicitly owner-authorized test number, **not a synthetic
  +916000... phone**, recorded in an existing CRM prospect or promoter. That
  exact phone must be allowed locally; obtain its opt-in and corresponding
  Communication consent evidence. Do not change an unrelated contact's number
  to receive an experimental send.
- No provider dispatch is attempted until you explicitly enable and approve
  a campaign in the CRM. API acceptance does not confirm WhatsApp delivery.

## Step 1: pull the code and edit existing private API environment

From the existing `C:\Users\Admin\Desktop\SaS` checkout, in PowerShell:

```powershell
git pull --ff-only origin main
notepad .\apps\api\.env
```

Keep your existing `DATABASE_URL`, `AUTH_SECRET`,
`UPI_MATCH_SECRET` and local Admin settings. The app loads the `.env` when
started inside `apps/api`. Add or update:

```dotenv
APP_ENV=development
LOCAL_DEMO_LOGIN_ENABLED=true
SAASYTO_INSTANCE_ID=YOUR_CONNECTED_INSTANCE_ID
SAASYTO_ACCESS_TOKEN=YOUR_PRIVATE_ACCESS_TOKEN
SAASYTO_RUNNER_SECRET=YOUR_DIFFERENT_RANDOM_SECRET_AT_LEAST_32_CHARS
SAASYTO_LOCAL_TEST_ENABLED=true
SAASYTO_LOCAL_TEST_PHONE=+919XXXXXXXXX
SAASYTO_SENDER_APPROVED=false
SAASYTO_DELIVERY_ENABLED=false
```

If a runner secret is not yet generated, execute:
`py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"`.
The phone **must be a real number whose owner authorized this pilot**, in
`+countrycode` format, with no spaces or brackets. Do not publish it.

Choose the activation moment only when you are ready to review an authorized
new campaign; **a campaign created before the cutoff cannot be approved**.
For India, PowerShell can generate the local time with offset:

```powershell
(Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')
```

Copy its output into `SAASYTO_ENABLE_AFTER` in `.env`. Verify the
machine's timezone is IST (`+05:30`). Then, only after confirming
sender authorization and the recipient's documented consent, explicitly
set both `SAASYTO_SENDER_APPROVED=true` and
`SAASYTO_DELIVERY_ENABLED=true`. Save the file.

**No delivery will occur simply because the settings are enabled.** The
Admin must still create a new campaign, perform a fresh recipient check
and approve it, and the private local worker must be running.

## Step 2: run local API, frontend and worker

Restart the API *after* any `.env` changes; from the repository root:

Terminal 1 — API (choose an unused port):

```powershell
cd C:\Users\Admin\Desktop\SaS\apps\api
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Terminal 2 — existing frontend (retaining your current `.env.local`):

```powershell
cd C:\Users\Admin\Desktop\SaS\apps\web
notepad .env.local
```

It should contain `API_INTERNAL_URL=http://127.0.0.1:8001` and your
existing demo login setting; do not put `SAASYTO_*` secrets here. Start
`npm run dev -- --port 3002`. Open
`http://localhost:3002/communication`.

Terminal 3 — local queue worker (private, loopback-only):

```powershell
cd C:\Users\Admin\Desktop\SaS\apps\api
.\.venv\Scripts\python.exe -m app.saasyto_local_worker --port 8001
```

The worker polls every 30 seconds. It never exposes a public HTTP port,
uses no proxy/redirect, sends the private runner token only to localhost
and prints aggregate attempt counts. For a *single manual* check instead
of continuous polling, use
`python -m app.saasyto_local_worker --port 8001 --once`.
Stop the worker with Ctrl+C.

## Immediate send from Communication — no local worker required

On the latest code, an unscheduled **Review & send** WhatsApp campaign can be
submitted directly from **Communication → Campaigns → Campaign results**.

1. Keep the selected sender's `SAASYTO_INSTANCE_ID` and `SAASYTO_ACCESS_TOKEN`
   in the backend-only `.env`. The connected sender must actually be online
   in Saasyto and authorized to send from the intended WhatsApp account.
2. For an owner-authorized, consented single-phone pilot, set
   `SAASYTO_LOCAL_TEST_ENABLED=true` and the exact
   `SAASYTO_LOCAL_TEST_PHONE=+countrycode...`, plus
   `SAASYTO_SENDER_APPROVED=true`, `SAASYTO_DELIVERY_ENABLED=true`,
   and an activation cutoff before **the new campaign**. Restart the API.
3. In Compose, choose **WhatsApp**, an audience that produces exactly **one**
   eligible recipient, and **Review & send** (not Plan for later). Enter the
   message. Continue to recipient review, then **Check recipients**.
4. When 1 eligible recipient is shown, click **Send WhatsApp now** and confirm.
   The Admin action stores a one-attempt approval, claims the recipient,
   submits the text to `POST /api/send`, and refreshes the CRM result.
   No separate worker is necessary for this case.
5. **Accepted by Saasyto** means *gateway submission only*. Open the intended
   recipient's WhatsApp chat and sender's WhatsApp history to verify receipt.
   If Rejected, Unknown, or Not sent, inspect the reason without blind retry.

Previously approved, queued, due-now local tests have a separate
**Send pending WhatsApp now** action. Attempts already claimed, unknown,
rejected, or submitted cannot be invoked again. No replays.

The protected manual endpoint `POST
/v1/communication/campaigns/{campaign_id}/saasyto/send-now` requires Admin
session, CSRF, development-mode localhost safeguards, explicit prior
campaign approval, exactly one queued recipient, and a due-now campaign.

**Scheduled campaigns and production batches still require the private
worker.** This change does not activate background scheduling, webhooks,
or unrestricted sending to all active contacts.

## Step 3: send from CRM (not Saasyto dashboard)

1. In the selected test person's CRM detail, ensure the correct
   WhatsApp number is recorded, `whatsapp_opt_in` is enabled with the
   owner's permission, and a Communication **opted-in** consent event
   exists with evidence reference for general WhatsApp outreach.
2. **Communication → Compose**. Create a **new** WhatsApp campaign after
   `SAASYTO_ENABLE_AFTER`, selecting an audience/segment whose live
   *eligible* recipient set contains **exactly the one allowlisted number**.
   The local pilot refuses campaigns with multiple eligible recipients.
3. **Communication → Campaigns → Review → Check recipients**.
   Check `1 Eligible`; if it shows `0`, fix consent/segment. If it shows
   `2+`, restrict the segment (not by disabling other people's consent).
4. Click **Approve WhatsApp delivery** and confirm. This queues a one-time
   send, not a separate Saasyto campaign.
5. With Terminal 3 running, click **Refresh delivery attempts** on the
   Campaigns review pane. The only accepted status initially available
   is `accepted_unverified`, not a delivery receipt. Verify actual receipt
   on the authorized phone and in Saasyto's message history.

The local pilot checks the phone allowlist on **approval, dispatch
eligibility, and final HTTP transport**. Changes to consent, opt-out,
CRM status, or approved phone after review can suppress a queued send.
No uncertain send is automatically retried.

## Limits and stop controls

- This is a controlled **single-phone pilot**. To message broader audiences,
  deploy/approve the production-grade transport instead; do not remove the
  local recipient allowlist or use `APP_ENV=test` to bypass it.
- Disable at any time by setting `SAASYTO_DELIVERY_ENABLED=false`,
  restarting API + worker, and stopping Terminal 3. Cancel queued campaigns
  in the CRM when appropriate; an already submitted WhatsApp message cannot
  be recalled.
- No inbound webhook is configured. Replies, delivered/read status, email,
  automatic 5th/20th reminders and payment-triggered WhatsApp messages are
  **not** activated by this change.
- QR-linked WhatsApp sessions may not have the same compliance guarantees
  as the official Meta WhatsApp Business Platform. Obtain sender and consent
  approvals before automatic business-initiated messages.

## If the CRM says accepted but the WhatsApp recipient sees nothing

The first local campaign has only confirmed **Saasyto gateway acceptance**.
That is not a WhatsApp delivery or read receipt. A previous accepted attempt
must not be repeated automatically; manually verify with the intended
recipient and the connected sender's WhatsApp chats.

1. Check the intended Saasyto instance is **connected** to the correct sender
   phone and active. The account must not be expired or disconnected.
2. Check the exact recipient number (with country code) on the CRM contact and
   the authorized phone's WhatsApp inbox. The CRM shows only masked numbers.
3. A bulk-campaign **Sent** report in Saasyto is not evidence about a separate
   `/api/send` single-message request. Do not confuse those report types.
4. New connector versions record safe error codes: `provider_rejected`,
   `provider_http_error`, `provider_timeout`, `network_error` and
   `unverified_provider_reply`. This does **not** expose the sender's token,
   phone numbers, or provider response bodies.
5. If the provider does not return a documented success indication, the CRM
   now records **unknown** rather than pretending it sent the message.
   Unknown, claimed, or timed-out attempts are not retried.
6. If a controlled test is authorized, create **a new campaign** after verifying
   the sender and a currently opted-in recipient. The local one-phone pilot
   still limits sending to a single explicitly allowlisted contact.

Historical `accepted_unverified` records are left unchanged. There is
currently **no authenticated delivery/read webhook** and no provider message-ID
reconciliation. Read / seen tracking must remain unverified until those
capabilities are confirmed in the provider's actual API for this sender.

### Existing consent is not hardcoded

Recording a real, evidence-backed WhatsApp opt-in is enough: it takes
precedence over an old false checkbox in the eligibility evaluator.
An explicit opt-out always wins. Simply changing someone to CRM Active
never creates a WhatsApp opt-in event. If the Foundation has a pre-existing
permission register, record or import its documented authorizations;
do not silently fabricate opt-in evidence for every active CRM record.
