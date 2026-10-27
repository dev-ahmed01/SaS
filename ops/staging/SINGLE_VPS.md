# InterServer — One VPS, protected SaS staging

This deploys **FastAPI, Next.js, PostgreSQL 16 and Caddy HTTPS** to a single
InterServer Ubuntu VPS. It builds on `compose.yaml` using the
`compose.single-vps.yaml` overlay. It does **not** migrate local sponsor
records or activate real WhatsApp sending. It is designed first for synthetic
team testing, not unreviewed production rollout.

## 0. Required infrastructure

- InterServer **Ubuntu 24.04 LTS** KVM VPS, recommended 4 slices/8 GB RAM;
  3 slices/6 GB can work for light usage but leaves less room for image builds.
  Choose plain Ubuntu with **no cPanel or WordPress image**.
- One domain/subdomain you control, e.g. `crm-test.yourdomain.com`.
- A DNS A record: `crm-test.yourdomain.com -> YOUR_VPS_PUBLIC_IP`.
  Remove any incorrect AAAA record. Initially set Cloudflare DNS records to
  DNS-only (not proxied) if you use Cloudflare for DNS.
- Firewall: inbound TCP 22 (prefer an SSH allowlist), TCP 80/443;
  optional UDP 443 for HTTP/3. **Do not expose 5432, 8001 or 3000.**
- SSH access to the new VPS, using SSH keys. Never paste a server root
  password, database DSN, private key or API token into a chat.

No VPS is provisioned or charged by this repository.

## 1. Install Docker on the VPS

SSH into the Ubuntu VPS from Windows PowerShell (substitute the IP):

```powershell
ssh root@YOUR_VPS_PUBLIC_IP
```

On **Ubuntu**, follow the official Docker Engine apt-repository instructions:
https://docs.docker.com/engine/install/ubuntu/ . At minimum, install
Docker Engine, `docker-buildx-plugin` and `docker-compose-plugin`.
On the VPS, verify:

```bash
docker --version
docker compose version
sudo apt-get update
sudo apt-get install -y git openssl python3
```

Restrict SSH, patch the OS and configure unattended security updates before
sharing the CRM publicly. Avoid running Docker in an untrusted user's shell.

## 2. Clone repository and create staging secrets

On the VPS:

```bash
git clone https://github.com/dev-ahmed01/SaS.git
cd SaS
git switch main
bash ops/staging/prepare-single-vps.sh crm-test.yourdomain.com ops@yourdomain.com
```

Use the real **staging DNS hostname and operations email**. The script
refuses to overwrite any existing configuration. It creates root-private
`ops/staging/.env`, `ops/staging/.env.api`, `ops/staging/.env.db`, and
`ops/staging/postgres-tls` certificates with secure random secrets.
These paths are Git-ignored and excluded from Docker build contexts.

The private TLS certificate is for the Docker-internal PostgreSQL connection
(`sslmode=require`); it encrypts that traffic, but doesn't verify the
database server identity against a private CA. All database containers are
on the **private Docker bridge only**. For production, use a managed Postgres
TLS endpoint with full CA verification and off-host backups.

## 3. Start private PostgreSQL and apply all migrations

Run **from the repository root**:

```bash
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml config --quiet

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml build

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml up -d db

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml \
  run --rm api python -m alembic -c alembic.ini upgrade head
```

The PostgreSQL data lives in a **named persistent Docker volume**, not in an
ephemeral container. Never run `docker compose down -v`. Migrations are
applied to this newly created staging database only, with **zero local donor
data copied**.

## 4. Create exactly one Admin interactively

```bash
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml \
  run --rm -it \
  -e BOOTSTRAP_ORGANIZATION="Emlen Foundation Staging" \
  -e BOOTSTRAP_ADMIN_EMAIL="YOUR_ADMIN_EMAIL" \
  api python -m app.bootstrap_admin
```

Replace `YOUR_ADMIN_EMAIL` with a real intended Admin address. Choose a
unique strong password **at the terminal prompt**; do not put it on the
command line or in `.env` files. The bootstrap prevents a second Admin.
No default user account or password exists on the hosted CRM.

## 5. Launch Caddy HTTPS + web + API

Make sure the DNS A record points at the InterServer VPS and ports 80/443
are reachable from the public internet before starting Caddy:

```bash
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml up -d

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml ps

curl --fail --silent --show-error https://crm-test.yourdomain.com/health/live
curl --fail --silent --show-error https://crm-test.yourdomain.com/health/ready
```

Replace the example URL with your actual hostname. **Both** health checks
must succeed with valid HTTPS and `{"status":"ready"}` on readiness.

The Next.js server resolves the hostname privately to the Caddy container
using a Docker DNS network alias. Its upstream HTTPS request therefore
retains correct TLS hostname verification **without** using a plaintext
internal API origin. Only Caddy publishes internet ports 80/443.

## 6. Test before inviting the team

1. Sign in with the fresh Admin and verify there are no donor records.
2. Create synthetic Prospects and Promoters. Test CSV/TSV import and export,
   follow-up calendar/time, editing, assignment and guarded deletion.
3. Verify Collections date, amount, month, recorded timestamp and payout
   ledger with synthetic entries.
4. Confirm unsupported actions report useful errors; confirm login cookies
   are secure and logs do not expose OTPs, contacts or secrets.
5. **WhatsApp OTP, campaign sends, automated reminders and acknowledgement
   transport remain OFF.** Do not flip production sender flags as part of
   first-time staging testing.
6. Review dashboard and listings on desktop/mobile and test a sign-out,
   fresh sign-in and return visit over HTTPS.
7. Take a successful database backup and test restoring it to a **separate**
   sandbox before using the CRM for real Foundation transactions.

## 7. Secure backups and routine management

Back up staging to a root-only folder **on the VPS** (then transfer the
encrypted archive to an independently secured off-host backup destination):

```bash
mkdir -p ~/sas-backups && chmod 700 ~/sas-backups
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml \
  exec -T db pg_dump -U sas_staging -d sas_staging -Fc \
  > ~/sas-backups/sas-staging-$(date -u +%Y%m%dT%H%M%SZ).dump
```

`pg_dump -Fc` contains personal/financial information if real records
exist: encrypt it before off-host transfer, enforce restricted retention,
and rehearse a restore. A backup that has not been restored and tested is
not proven usable. Configure a separately monitored scheduled backup later;
container volumes alone are **not** backups.

Troubleshoot without revealing secrets:

```bash
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.yaml -f ops/staging/compose.single-vps.yaml \
  logs --tail=100 api web proxy db
```

Do not paste raw live logs containing private phone numbers, tokens or
database URLs into public issues or chats.

## Known limits

This is a **tested deployment blueprint**, not evidence that a VPS has
already been purchased, DNS changed, HTTPS issued, or live WhatsApp verified.
The app is self-managed on a budget VPS. Keep real donor data on the existing
local machine until backups, consent controls, administration, HTTPS and live
messaging sender approval have passed an explicit cutover review.
