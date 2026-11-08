# SaS → Contabo: production deployment and controlled cutover

This is a **runnable deployment procedure**, not evidence that the VPS, sender or records have been inspected. Source code and CI tests cannot approve the Foundation's privacy/finance policy or verify delivery to a real WhatsApp device. Use the existing Foundation release acceptance checklist and signed approval dossier for live records.

## Architecture

- One shared Caddy HTTPS gateway binds public 80/443. Deploy SaS first; WE and AE can be added later as optional Caddy sites.
- SaS production stack `ops/contabo/compose.production.yaml` has its own Compose project, PostgreSQL 16 persistent volume, FastAPI and Next.js containers. No app/db container publishes a host port.
- Private CA-signed PostgreSQL TLS with **verify-full**; the signing CA key is kept on the operator host, not mounted into containers. Renew the DB leaf certificate before its 365-day expiry.
- WhatsApp provider secrets stay inside `ops/contabo/.env.api`, never inside web/Next.js. A worker is an explicit Compose **messaging profile**, not started on deployment.
- The sender, campaign worker, standing IST reminders and OTP integration all default **OFF**; WhatsApp can later be enabled with the existing, reviewed Saasyto provider settings without altering code.

## 1. Ubuntu VPS before deployment

Use your existing nonroot `deploy` SSH account and sudo privilege. Apply OS updates, SSH key-based access, restrict SSH ingress, enable security updates, and install Docker Engine, Buildx and Docker Compose plugin using the official Ubuntu installation instructions. Confirm Docker configuration and firewall rules before creating a Docker service. Docker's published ports can bypass some host firewall controls; only the shared Caddy gateway should publish 80/443, never 5432/8001/3000.

Do **not** run another Caddy/Nginx service binding the same ports. Check `docker ps` and `sudo ss -lntup` first. Verify the VPS has sufficient free RAM/storage and a separately backed-up off-host destination for encrypted dumps. Keep source checkout and server secrets readable only to authorized deploy operators; Docker group membership grants high host privileges.

## 2. Freeze and check the release

After the PR has been merged and its final `main` commit has passing CI:

```bash
git clone https://github.com/dev-ahmed01/SaS.git
cd SaS
git switch main
git pull --ff-only
git rev-parse HEAD
docker --version
docker compose version
docker network inspect emlen_ingress >/dev/null 2>&1 || docker network create emlen_ingress
```

Record the release SHA and CI links. Do not checkout an arbitrary unreviewed branch or put `.env` secrets into Git.

## 3. Prepare the SaS production secrets exactly once

Decide the **real** SaS admin dashboard hostname and configure its A record to the Contabo VPS; do not use a sample hostname or a Cloudflare tunnel as the canonical production origin.

```bash
bash ops/contabo/prepare-production.sh sas.your-real-domain.tld
```

This creates private `ops/contabo/.env`, `.env.db`, `.env.api` and `postgres-tls/` once. It refuses to overwrite existing data/configuration, generates independent secrets and signs a PostgreSQL TLS leaf for `db`. **Store a protected copy of all durable secrets, CA material, encryption keys and operator access in an approved secret manager/off-host vault.** Never paste them into chat or a CI log.

**If importing existing Foundation records:** you must preserve the existing source `UPI_MATCH_SECRET` (and any OTP/provider state that must continue to verify) rather than using the freshly generated replacement. Inventory source DB revision, organization IDs and current data before deciding which secrets to retain. Do not regenerate a previously used matching secret.

The script intentionally does NOT contain Saasyto provider instance ID/token and does NOT enable sending.

## 4. Configure the single HTTPS gateway for SaS first

```bash
cp ops/shared-vps/.env.example ops/shared-vps/.env
chmod 600 ops/shared-vps/.env
```

Edit `ops/shared-vps/.env` privately to set the SAME hostname as `ops/contabo/.env`, a real `ACME_EMAIL`, `SAS_API_UPSTREAM=sas-prod-api:8001`, and `SAS_WEB_UPSTREAM=sas-prod-web:3000`. WE/AE hostnames are **not required** for SaS. They can be added later as files in `ops/shared-vps/sites/`.

Only the central gateway should terminate HTTPS. SaS's web server requests its own exact `https://SAS_HOST` origin internally, which resolves through the gateway Docker network alias with the public certificate name still verified. Never bypass origin validation or trust checks to work around incorrect DNS.

## 5. Choose ONE data initialization path

**A. New empty installation (no imported users/records):**

```bash
bash ops/contabo/preflight.sh
docker compose --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml build
docker compose --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml up -d db
docker compose --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml \
  run --rm api python -m alembic upgrade head
docker compose --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml \
  run --rm -it -e BOOTSTRAP_ORGANIZATION="Emlen Foundation" \
  -e BOOTSTRAP_ADMIN_EMAIL="YOUR_APPROVED_ADMIN_EMAIL" \
  api python -m app.bootstrap_admin
```

Choose the Admin password only at the interactive terminal, not on the command line. Replace the example Admin email. Do not seed fake production donors.

**B. Migration of an existing database:** after a separately authorized read-only source inventory and backup, restore its dump into a NEW EMPTY PostgreSQL target before any Alembic upgrade. **Do not** run path A's migrations/seed first and then restore over already created tables. Inspect the source revision, secrets and foreign-key/ledger totals, then apply any required forward migration once. Do not use `--clean` against a live database or blindly downgrade financial migrations. A disposable rehearsal and independently witnessed restore must pass before the live cutover.

## 6. Start application and HTTPS, then verify

```bash
docker compose --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml up -d api web
docker compose --env-file ops/shared-vps/.env \
  -f ops/shared-vps/compose.yaml config --quiet
docker compose --env-file ops/shared-vps/.env \
  -f ops/shared-vps/compose.yaml up -d
bash ops/contabo/smoke.sh sas.your-real-domain.tld
```

Smoke checks include valid HTTPS, `/health/live`, database+migration readiness, login page and unauthenticated session rejection. Confirm a fresh login, logout, HttpOnly/Secure cookies, permissions, CSRF, no public donor API data and correct India-month accounting manually. Do a synthetic browser UAT of Promoters, Prospects, Collections, Payouts and Communication.

**Stop if HTTPS, readiness, private DB, audit counts or access-control checks fail.** Do not enable sending as a fix for OTP errors during migration.

## 7. Encrypted backups and independently witnessed restore

Install `age` on the VPS. Generate/store the **private age identity off-host**, and configure only the corresponding `age1...` PUBLIC recipient on the VPS:

```bash
export SAS_BACKUP_AGE_RECIPIENT="age1...approved-public-key..."
bash ops/contabo/backup-database.sh
```

The backup streams `pg_dump -Fc` directly into age encryption, writes a SHA-256 checksum and never saves a plaintext dump to disk. Copy both the encrypted dump and checksum to independent off-host storage, with a documented retention policy. Set up a protected scheduled invocation and **alert on missing/failed backups**. Docker volumes alone are not backups.

Use `ops/contabo/restore-drill.sh` only with the approved private age identity, backup, checksum and explicit `SAS_RESTORE_ACK=ISOLATED_NEW_DATABASE`. It creates a separate named Compose project/volume, restores without touching the live `sas-production` volume, and leaves the recovery target for a finance/tenant integrity reviewer. A restored schema version is not by itself proof of record integrity: reconcile organization/ledger counts and signed finance samples, then measure RPO/RTO.

## 8. WhatsApp after the cutover (your existing tested provider)

Your local Saasyto test is useful evidence of sender connectivity, but it does not prove that **this new VPS** is configured, permitted to send to all CRM recipients, or receiving provider delivery callbacks. Preserve the current, working Saasyto integration and its consent/STOP checks. In private `.env.api`, set the verified `SAASYTO_INSTANCE_ID`, `SAASYTO_ACCESS_TOKEN`, existing/private `SAASYTO_RUNNER_SECRET`, and a NEW offset-aware `SAASYTO_ENABLE_AFTER` cutoff chosen immediately before the first approved campaign. Never enable with an old cutoff just to replay test backlog.

After the isolated, real-device, consented post-migration pilot and authorized sender signoff, an operator may **explicitly** enable the proper flags:
- `SAASYTO_SENDER_APPROVED=true` and `SAASYTO_DELIVERY_ENABLED=true` for approved one-off sends
- `OTP_SAASYTO_ENABLED=true` only if the sender is also authorized for authentication codes; requires stable `OTP_SECRET`
- `SAASYTO_WORKER_ENABLED=true` only when the approved campaign worker should dispatch existing reviewed queues
- `SAASYTO_AUTO_REMINDERS_ENABLED=true` only under independent 5th/20th reminder approval (never implicit)

Restart API to read the changed environment. Start **one** worker explicitly, if approved:

```bash
docker compose --profile messaging --env-file ops/contabo/.env \
  -f ops/contabo/compose.production.yaml up -d worker
```

For an emergency stop, set `SAASYTO_DELIVERY_ENABLED=false`, `SAASYTO_WORKER_ENABLED=false`, `OTP_SAASYTO_ENABLED=false`, restart API and stop the worker. Provider-accepted messages cannot be recalled. Check queued/unknown outcomes without blindly resending.

## 9. Subsequent code updates and rollback

Keep donor data in the persistent PostgreSQL volume; code lives in version-controlled web/API images. Deployment does not mean losing the ability to edit pages or logic. Use a reviewed CI-green commit, take an encrypted backup, check the migration compatibility, then build and replace affected containers with `docker compose ... up -d --build api web`. **A single web/API replica can experience a short restart or a brief outage during these updates; this is not zero-downtime deployment.** Schedule disruptive schema migrations with a maintenance window and verify health immediately after.

Record the previous compatible image tags/SHA before release so application binaries can be restored. Do not run `docker compose down -v`, remove PostgreSQL volumes, reset private CA/UPI secret, or rollback the database via uncontrolled Alembic downgrades. Never retry ambiguous WhatsApp submissions after crashes.

**External items remaining at handoff:** exact Contabo host/SSH state, DNS A record, TLS issuance, production secret custody, real backup source and off-host destination, protected GitHub main, Foundation privacy/finance signoff, actual restore result, live post-cutover WhatsApp consent/device test and final UAT. Code review cannot mark those completed.
