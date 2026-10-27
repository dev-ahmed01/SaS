# SaS — InterServer VPS protected staging

**Starting with one InterServer VPS? Use [SINGLE_VPS.md](SINGLE_VPS.md)** for the
private PostgreSQL + Caddy + API + Next.js deployment. The instructions below
are for deployments with an already provisioned **external TLS PostgreSQL** service.

Deploys **Next.js + FastAPI** on an InterServer Linux VPS behind **Caddy HTTPS**.
This is a staging bundle for Amaan's team to test workflows and performance,
**not** production approval. It does not provision an InterServer account, domain,
database, payment gateway, or real WhatsApp delivery.

## Prerequisites

- Ubuntu/Debian VPS with Docker Engine and the Compose plugin; inbound TCP
  80/443, and UDP 443 for optional HTTP/3; SSH restricted to trusted operators.
- Dedicated DNS **A** record for `STAGING_HOST` pointing at the VPS. Do not
  reuse a Cloudflare Quick Tunnel or the live Foundation CRM hostname.
- An **isolated, empty staging PostgreSQL database** with a TLS endpoint
  (`sslmode=require`, preferably `verify-full`). A managed Postgres instance
  is simplest; an InterServer-managed PostgreSQL server is also possible if
  TLS is properly configured. The local development database and donor records
  must not be copied.
- Admin's own email address and a unique strong password to be entered once
  interactively. No seed/demo login is enabled.
- Access to official DNS and VPS controls. Do not send tokens or passwords in
  chat, commit them to Git, or paste them into support tickets.

## 1. Provision private environment on the VPS

In the checked-out SaS repository:

```bash
cp ops/staging/.env.example ops/staging/.env
cp ops/staging/.env.api.example ops/staging/.env.api
chmod 600 ops/staging/.env ops/staging/.env.api
```

Edit `ops/staging/.env` and set a genuine staging hostname and operations
email. Edit `ops/staging/.env.api` with the **staging-only** PostgreSQL TLS
connection string, separate 48+ character `AUTH_SECRET`,
`UPI_MATCH_SECRET`, and `OTP_SECRET`. Generate them locally with:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Run this three times. Keep the final keys in a secure password manager.
Database values with URL-special characters need URL-encoding. Staging
requires `APP_ENV=staging` and **must not** use `LOCAL_DEMO_LOGIN_ENABLED`.

Compose explicitly forces Pabbly/Meta/Saasyto sending and OTP switches off,
independent of what the API env file says. Do not alter that safety default
for team UI testing. Organization automations also default to disabled.

## 2. Validate and build containers

```bash
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml config --quiet
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml build --pull
```

This intentionally does **not** expose an API or database port on the VPS.
Caddy is the only internet-facing container and automatically provisions
HTTPS for the configured hostname. Next.js fetches the FastAPI endpoints over
the **same HTTPS origin**, routing only `/v1/*` and health endpoints to API.
BFF session and CSRF checks remain enabled.

## 3. Migrate the empty staging database before starting

```bash
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml \
  run --rm --no-deps api python -m alembic -c alembic.ini upgrade head
```

Never run migrations against the donor production database. On staging
refreshes: take and verify an isolated encrypted backup first, check its
migration head, and rehearse restore before applying a schema update.
**Rollback the app image independently; do not blindly downgrade database
migrations containing stage identity or financial records.**

## 4. Provision the private Admin once

```bash
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml \
  run --rm --no-deps -it \
  -e BOOTSTRAP_ORGANIZATION="Emlen Foundation Staging" \
  -e BOOTSTRAP_ADMIN_EMAIL="admin-staging@example.org" \
  api python -m app.bootstrap_admin
```

Replace the example Admin email; enter and confirm the password at the secure
TTY prompt. The command refuses to provision a second Admin.

## 5. Start and validate

```bash
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml up -d
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml ps
curl --fail --silent --show-error "https://YOUR-STAGING-HOST/health/live"
curl --fail --silent --show-error "https://YOUR-STAGING-HOST/health/ready"
```

Replace `YOUR-STAGING-HOST` with the exact DNS name. Require both checks to
pass (not just an HTTP redirect). Visit the protected staging site, sign in
with the explicitly provisioned Admin, and verify:

- No local demo login, no real sponsorship/donor data, no outgoing sender
- Prospect create/edit, same-name different-phone validation, CSV import/export
- OTP activation **disabled by configuration** rather than silently bypassed
- Follow-up stage selection, next-date/time in IST and activity timeline
- Collections add, reversal/correction and Received This Month filter
- Promoter Active Sponsors / Inactive Prospects counts, mobile/desktop layouts
- Audit events and tenant isolation; no real WhatsApp receipt or OTP submitted
- HTTPS valid certificate, secure cookies, restricted SSH and daily DB backup

For smoke and regression tests, use **synthetic** records on the staging DB.

## 6. Operations and handoff

```bash
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml logs --tail=100 api
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml logs --tail=100 web
docker compose --env-file ops/staging/.env -f ops/staging/compose.yaml logs --tail=100 proxy
```

Avoid exporting raw application logs containing contact data. Keep encrypted
PostgreSQL backups **off-host**, confirm a successful restore in a separate
database, and restrict backup/DB accounts by least privilege. Update the
containers only after GitHub CI is green and a staging backup is tested.

Staging UAT should be done by named operators through the CRM Admin login.
For additional network restriction, add an approved access gateway and verify
that Next.js server-side `API_INTERNAL_URL` calls can still reach the
HTTPS API; do not place an unauthenticated public demo behind a secret URL.

### Known limits

- This bundle does not install or administer InterServer's VPS, register DNS,
  configure an external PostgreSQL instance, or collect performance figures.
- Saasyto direct submission only confirms an API-side result, **never** a
  recipient delivery/read. Live sending needs its own approved test and
  monitored provider receipts.
- Do not flip outbound messaging flags to true just to exercise the UI.
