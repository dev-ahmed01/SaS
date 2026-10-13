# Phase 03 — Admin authentication runbook

The public repository contains **no credentials**, no development Admin default, and no public registration route. The only initial role is **Admin**.

## Before running locally

1. Provision PostgreSQL and copy `apps/api/.env.example` to `apps/api/.env`.
2. Set `DATABASE_URL` for your development PostgreSQL instance.
3. Generate `AUTH_SECRET` using `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Use a unique secret per environment and protect it in hosting secrets; **do not commit it**.
4. Run `python -m alembic upgrade head` inside `apps/api`.
5. Set `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ORGANIZATION` in your shell; optionally seed values with `BOOTSTRAP_AMOUNT_PAISE`, `BOOTSTRAP_SPONSOR_DAY`, `BOOTSTRAP_PROMOTER_DAY`, `BOOTSTRAP_INACTIVITY_MONTHS`. The approved sponsorship default is 25000 paise (₹250), overrides must be positive multiples of 25000 paise, and inactivity is fixed at two completed IST months.
6. Run `python -m app.bootstrap_admin` and enter a strong password twice at the interactive prompts. Provisioning fails if an Admin already exists.
7. Start `uvicorn app.main:app --host 127.0.0.1 --port 8000`.

The frontend requires `API_INTERNAL_URL=http://127.0.0.1:8000` in `apps/web/.env.local`. Use `npm ci && npm run dev` from `apps/web`.

## Security model

- Database-backed opaque sessions, SHA-256 token digests, 8-hour fixed lifetime, server-side revocation on sign-out.
- Cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` in staging/production.
- Non-read API requests require a CSRF token bound to the current session; the browser uses same-origin Next.js APIs.
- Single-Admin-only authorization; inactive Admin records lose access immediately.
- Login attempts are throttled using DB-backed hashed email/network markers. Add host-level rate limiting and monitoring before broad exposure.
- Only allow the frontend to reach FastAPI through the same-origin BFF in production. Configure a private API address if infrastructure permits; never expose PostgreSQL directly to browsers.
- The production system requires HTTPS, secure secret rotation procedures, admin recovery process and regularly tested PostgreSQL backups.
- Audit logs contain before/after business setting values, not secrets.
- The WhatsApp automation setting remains disabled; Phase 11 provides the gated messaging integration.

## Recovery and secrets

There is **no email-password reset** in Phase 03. Recovery requires a verified, documented operations procedure by an authorized maintainer, including session revocation and audit; never manually edit the password hash without an approved recovery workflow. A unique secret must be configured in each deployment. Changing `AUTH_SECRET` invalidates CSRF signatures and login-throttle hashes but does not itself revoke existing database sessions; explicitly revoke sessions during key rotation.

## Deployment gate

Do not deploy actual sponsor or finance data until independent browser, access-control, backup/restoration, CSRF/origin, and operations reviews are completed.


## Trusted Vercel Admin login identity

The Next.js gateway signs Vercel-managed original client IPs using the
server-only `AUTH_SECRET` shared with FastAPI; the API verifies this signature
before applying cross-account network throttling. Unsigned or forged headers
are ignored, and untrusted reverse proxies receive account-scoped throttling
to prevent shared-proxy lockout. Both deployments need the same secret.

In staging, independently verify that the production edge overwrites incoming
forwarded IP headers and test abusive requests from two different client
networks. A platform WAF/rate-limit is still required; non-Vercel
self-hosted proxies must not be trusted without their own security review.
Raw client IPs are never persisted in the login attempts table.
