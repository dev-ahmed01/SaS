# WhatsApp campaigns + verified prospect activation

## How activation works

This follows the independently developed OTP-gated activation workflow in
PR #65. The Admin creates a prospect (CRM Inactive), opens Prospect Details,
clicks **Verify and activate**, requests the WhatsApp OTP and asks the
recipient for the received six digits. The validated OTP and stage activation
are one database transaction. First activation needs no reason; subsequent
reactivation needs a reason **and a fresh OTP**. Regular manual stage API calls
cannot bypass this. Payments remain a separate lifecycle.

**OTP delivery is through the approved Meta WhatsApp authentication template
sender.** The working Saasyto free-text API does not prove support for an
approved AUTHENTICATION copy-code template. Use a restricted Meta system user
token, the approved authentication template and registered sender phone ID.
A Saasyto credential cannot replace these settings.

This follow-up adds one optional **Saasyto registration-active notice** after
OTP activation. It only sends when the contact has documented general-message
WhatsApp permission and has not opted out. An explicit opt-out suppresses it.
The notice has no code and does not assert payment. It is submitted once
after the OTP is irreversibly consumed; gateway acceptance is not delivery.
No automatic retry if the outcome is unknown.

## Replace settings, not the entire .env

Back up your existing private `apps/api/.env` and preserve
`DATABASE_URL`, `AUTH_SECRET`, `UPI_MATCH_SECRET`, unrelated messaging
integrations and existing sender credentials. Never commit the file.

**Local demo and production are different environments**. Your protected
localhost demo is intentionally limited to one allowlisted phone. Changing
`SAASYTO_LOCAL_TEST_ENABLED=false` in local development cannot enable bulk
sending because backend configuration explicitly blocks that combination.
Production requires a real separate TLS PostgreSQL database, secure auth and
a running private worker.

Example **production backend** block; placeholders are not literal values:

```dotenv
APP_ENV=production
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>/<db>?sslmode=require
AUTH_SECRET=<existing-secure-auth-secret>
UPI_MATCH_SECRET=<existing-stable-hmac-secret>

SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_INSTANCE_ID=<foundation-connected-sender-id>
SAASYTO_ACCESS_TOKEN=<rotated-private-token>
SAASYTO_RUNNER_SECRET=<unique-32-plus-character-random-secret>
SAASYTO_ENABLE_AFTER=<current-IST-datetime-with-offset>
SAASYTO_SENDER_APPROVED=false
SAASYTO_DELIVERY_ENABLED=false

OTP_DELIVERY_ENABLED=false
OTP_SECRET=<separate-32-plus-character-secret>
OTP_META_ACCESS_TOKEN=<restricted-meta-system-user-token>
OTP_META_PHONE_NUMBER_ID=<sender-phone-id>
OTP_META_TEMPLATE_NAME=<approved-authentication-template-name>
OTP_META_TEMPLATE_LANGUAGE=en_US
OTP_META_GRAPH_VERSION=v23.0
OTP_ACTIVATION_NOTICE_ENABLED=false
```

PR #65 makes OTP verification mandatory for activation when the provider
is enabled. **There is no `OTP_ACTIVATES_PROSPECT` flag in that workflow.**
Do not add one to your final production configuration.

### Activation cutoff

Generate the current time in IST in **Windows PowerShell**:

```powershell
[datetimeoffset]::UtcNow.ToOffset([timespan]::FromMinutes(330)).ToString("yyyy-MM-ddTHH:mm:sszzz")
```

For example, `2026-10-26T09:30:00+05:30` shows the format, not the
actual current time. Copy the command output into `SAASYTO_ENABLE_AFTER`
immediately before enabling the first production campaign. It gates
**campaign creation time**, not when you registered the Saasyto sender;
older plans never become an automatic backlog.

Generate a separate runner secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Never paste that secret in chat or screenshots. Reuse **exactly the same**
`SAASYTO_RUNNER_SECRET` in the API and its private worker, which needs:

```dotenv
SAS_API_PUBLIC_ORIGIN=https://<your-real-API-host>
SAASYTO_RUNNER_SECRET=<the-exact-same-private-secret>
```

Run on an always-on VPS:

```sh
python scripts/saasyto_tick.py --loop --interval-seconds 60
```

or schedule the one-shot `python scripts/saasyto_tick.py` once per minute.
Use one scheduling strategy. Do not use the web frontend origin for the
worker. The worker itself does not need the Saasyto account token.

### Switching on

1. Verify the connected sender and a single authorized live recipient.
   Check real WhatsApp receipt; API acceptance alone does not establish it.
2. Apply production migrations and verify HTTPS/PostgreSQL and secure Admin
   login. Start one private worker with matching secrets.
3. When the Foundation has documented sender and consent approval, turn
   `SAASYTO_SENDER_APPROVED=true` and `SAASYTO_DELIVERY_ENABLED=true`
   on the production API, then redeploy/restart the API.
4. Independently provision the real Meta WABA, approved **AUTHENTICATION
   Copy Code** template, system-user token and phone-number ID. Test one OTP,
   then set `OTP_DELIVERY_ENABLED=true` and restart API.
5. Only after separate general-message consent and one test activation notice
   succeed, set `OTP_ACTIVATION_NOTICE_ENABLED=true` and restart API.

**No need for each recipient to have a Saasyto account**. Recipients simply
need active WhatsApp, the relevant consent, and a valid number recorded in
the CRM. For multi-recipient campaigns use live Active/All audience review,
explicit approval and the private worker. No message sends merely by
registering a prospect or creating a campaign.

Neither GitHub CI nor this configuration guide can prove the actual provider
sender is online or a message has arrived on a device; production signoff
remains a separate controlled end-to-end test.
