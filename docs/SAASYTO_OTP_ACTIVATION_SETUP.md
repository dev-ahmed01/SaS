# Sponsor a Salah — environment, activation cutoff and OTP onboarding

## Keep local and production configuration separate

**Do not paste a replacement .env over your current local environment.**
Preserve the original `DATABASE_URL`, `AUTH_SECRET`, `UPI_MATCH_SECRET`,
Saasyto credentials, and previously configured unrelated features. Back up
your private `apps/api/.env` outside Git first. Never paste tokens in chat,
commit them, screenshot them or put them in `NEXT_PUBLIC_*`.

Current localhost demo deliberately protects **one allowlisted recipient**.
To send to all eligible database prospects, deploy the production API with a
separate TLS PostgreSQL database and one private worker. Setting
`SAASYTO_LOCAL_TEST_ENABLED=false` in a localhost demo does **not** lift the
development restriction; `APP_ENV=production` cannot be combined with the
local-demo database or login.

## Production API environment

Example placeholders ONLY. Set actual values as API host protected secrets.
Production database/authentication fields may already exist: do not rotate
them casually.

```dotenv
APP_ENV=production
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://<user>:<password>@<host>:5432/<db>?sslmode=require
AUTH_SECRET=<existing-or-new-long-random-auth-secret>
UPI_MATCH_SECRET=<existing-stable-upi-hmac-secret>

SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_INSTANCE_ID=<connected-sender-instance-id>
SAASYTO_ACCESS_TOKEN=<rotated-private-provider-token>
SAASYTO_RUNNER_SECRET=<new-private-random-secret-32-plus-characters>
SAASYTO_ENABLE_AFTER=<fresh-offset-aware-IST-date-time>
SAASYTO_SENDER_APPROVED=false
SAASYTO_DELIVERY_ENABLED=false

OTP_DELIVERY_ENABLED=false
OTP_ACTIVATES_PROSPECT=false
OTP_ACTIVATION_NOTICE_ENABLED=false
OTP_SECRET=<separate-random-secret-32-plus-characters>
OTP_META_ACCESS_TOKEN=<restricted-meta-system-user-access-token>
OTP_META_PHONE_NUMBER_ID=<numeric-meta-phone-id>
OTP_META_TEMPLATE_NAME=<approved-authentication-copy-code-template-name>
OTP_META_TEMPLATE_LANGUAGE=en_US
OTP_META_GRAPH_VERSION=v23.0
```

The `OTP_*` transport currently uses **Meta WhatsApp Cloud API**, not
Saasyto's arbitrary text-message endpoint. Standard WhatsApp authentication
templates have special approved copy-code button and wording requirements.
A working Saasyto free-text campaign does **not** establish that Saasyto
can send compliant OTP templates. Do **not** paste a Saasyto key into
`OTP_META_ACCESS_TOKEN`.

### Getting the activation cutoff (Windows PowerShell)

Run on your Windows machine **immediately before first enabling** sending:

```powershell
[datetimeoffset]::UtcNow.ToOffset([timespan]::FromMinutes(330)).ToString("yyyy-MM-ddTHH:mm:sszzz")
```

Example *format* (not necessarily your actual current time):

```text
2026-10-26T09:30:00+05:30
```

Paste the result after `SAASYTO_ENABLE_AFTER=`, with no quotation marks or
angle brackets. The value is an **IST activation boundary**, not the date
the provider account was created. Only campaigns **created after** that instant
can be approved for sending, preventing old test campaigns from being
accidentally dispatched. Keep a stable value once production campaigns exist;
avoid moving it backwards to resurrect old backlog.

`OTP_DELIVERY_ENABLED` is independent of this cutoff. OTP verification and
activation cannot be enabled by merely setting Saasyto delivery to true.

### Getting a runner secret

Generate locally in PowerShell (using your backend Python interpreter):

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate a **separate** secret for `SAASYTO_RUNNER_SECRET`, `OTP_SECRET`,
and (if initially provisioning) `AUTH_SECRET`. Store them only as secrets.
Do not rotate stable secrets that protect existing payment identifiers or
outstanding OTP challenges casually.

### Safe switch-on sequence

1. Confirm the Foundation's sending WhatsApp account is actually connected,
   licensed/authorized and can reach one explicitly consented real test phone.
2. Confirm live PostgreSQL migrations (`cd apps/api; python -m alembic upgrade head`),
   API authentication, documented permission and safe STOP handling.
3. Start exactly one private production worker with the same runner secret
   as the API. The worker needs
   `SAS_API_PUBLIC_ORIGIN=https://<your-production-API-host>` and
   `SAASYTO_RUNNER_SECRET=<same-as-api>` only. Do **not** give it the Saasyto
   access token.
4. After the controlled test has succeeded, set on the **API** host:
   `SAASYTO_SENDER_APPROVED=true` and `SAASYTO_DELIVERY_ENABLED=true`.
   Restart/redeploy API; a draft is not sent until explicitly approved.
5. For OTP, separately provision Meta WABA/phone number, a restricted system
   user token and an approved **AUTHENTICATION → Copy Code** template in
   WhatsApp Manager. Verify the sender and template in your Meta account.
   Then set `OTP_DELIVERY_ENABLED=true` and
   `OTP_ACTIVATES_PROSPECT=true`; restart API.
6. If opted-in new sponsors should receive an activation notification, set
   `OTP_ACTIVATION_NOTICE_ENABLED=true` only after testing it and verifying
   an actual **general WhatsApp communication opt-in** exists. This requires
   Saasyto sending already enabled and uses the approved sender's text API.

## Prospect registration and verification

- New prospect is CRM-Inactive and payment lifecycle is `new`.
- In Prospect Details the Admin clicks **Send verification code**; the
  six-digit OTP is sent using a Meta-approved authentication template.
- Code expires in 10 minutes, has resend cooldown and attempt limits.
  An incorrect, expired or reused code **cannot** activate a prospect.
- On a correct code, if `OTP_ACTIVATES_PROSPECT=true`, a never-paid,
  CRM-Inactive new registration becomes **CRM-Active** in one transaction,
  with stage-transition and audit history. Existing missed-payment inactive
  sponsors are not silently reactivated.
- Manual Mark Active cannot bypass OTP for these newly registered sponsors.
- If their verified phone is changed, the newly activated sponsor goes
  CRM-Inactive until a fresh OTP is completed.
- The payment lifecycle remains **new / never paid** until an actual payment
  is recorded. Being CRM-Active does not count as money received.
- If general WhatsApp permission is documented and
  `OTP_ACTIVATION_NOTICE_ENABLED=true`, a short registration-active
  confirmation is attempted once through Saasyto. If the contact opted out
  or has no evidence of permission, no follow-up is submitted. An accepted
  gateway response is **not a delivered/read receipt**.
- Do not confuse an OTP request (initiated by Admin with sponsor agreement)
  with blanket marketing consent or activation-message permission.

## Campaigns to multiple CRM contacts

Production campaigns can include contacts registered directly in Prospects,
not just demo entries. **Active** selects CRM-Active contacts;
**All contacts** can include not-yet-Active registrations with appropriate
consent. In Communication, check recipients and approve before the private
worker processes queued messages. The worker rechecks live permission and
opt-outs and does not automatically retry unknown outcomes.

To inspect pending/suppressed/accepted attempts, open Campaign results.
For any result marked accepted, check the real recipient phone and Saasyto
sender history; verified webhook delivery/read integration is still pending.

## Important limitations

- Changing your local demo .env cannot turn that instance into a supported
  multi-recipient production sender. Deploy and validate the production API.
- These steps do not create a Meta WABA, approve an OTP template, configure
  hosting or prove end-to-end phone delivery on your behalf.
- If you want Saasyto itself to carry authentication codes, obtain the
  provider's documented **approved authentication-template API** contract,
  including sender type and callback semantics, before changing the OTP
  adapter. The working `POST /api/send` free-text endpoint is insufficient.
