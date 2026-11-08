# SaS on a shared Contabo VPS — isolated staging first

**NOT a production authorization.** This is the SaS-specific migration preparation for a Contabo Ubuntu VPS also hosting the Workspace by Emlen and Accom by Emlen dashboards. SaS has a separate PostgreSQL data volume, API, and web image. All three applications must use **one** host-wide HTTPS ingress proxy, rather than three separate Caddy containers trying to bind ports 80/443. Do not run `compose.single-vps.yaml` alongside this topology.

## Boundaries and prerequisites

- Use only synthetic records. No donor database copy, WhatsApp delivery, OTP, reminder worker, or real financial transactions during staging.
- The VPS host must be patched, use SSH key authentication, restrict inbound 22 to trusted IPs, and expose only 80/443 for HTTPS. Never publish PostgreSQL, API, or Next.js ports.
- Confirm the repo commit passed backend/frontend CI and that owner-approved branch protections are active. A green build does not prove a live deployment.
- Ensure a dedicated DNS name (for example, `sas-staging.example.org`) points to the VPS. Use real operator-approved DNS, not the placeholder.
- Install Docker Engine + Docker Compose plugin and create the host-wide network **once**: `docker network create emlen_ingress`. Another app should reuse this network, not recreate or delete it.
- The **single shared Caddy** instance should join `emlen_ingress` and own host 80/443. The central Caddy configuration is an infrastructure-level concern, not deployed by SaS.
- In the shared Caddy service's `emlen_ingress` network configuration, create a DNS alias for the **exact SaS staging hostname**. This allows the Next.js BFF to call `https://<sas-staging-host>` over the Docker network while still verifying the real hostname certificate. Without this alias, the web container might resolve the public IP and fail due to hairpin routing.
- Do not deploy WE/AE until each of their own ports, databases, secrets and restore paths are separately audited.

## Prepare the private SaS stack

From a fresh checkout at the selected CI-verified commit on the VPS:

```bash
bash ops/staging/prepare-single-vps.sh sas-staging.example.org ops@example.org

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.shared-ingress.yaml config --quiet

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.shared-ingress.yaml build

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.shared-ingress.yaml up -d db

docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.shared-ingress.yaml \
  run --rm api python -m alembic -c alembic.ini upgrade head
```

The preparation script creates fresh root-private staged credentials and PostgreSQL internal TLS certificates. Never commit or paste their contents, never overwrite an existing `.env`, and do not use these synthetic-stage credentials for production. The internal `sslmode=require` transport encrypts private network DB traffic but does **not** give verified server identity; production should have a validated certificate/CA and independently secured off-host backups.

Create an Admin interactively with the documented `python -m app.bootstrap_admin` run command in `ops/staging/SINGLE_VPS.md`. After configuring the shared proxy and testing HTTPS certificate issuance:

```bash
docker compose --env-file ops/staging/.env \
  -f ops/staging/compose.shared-ingress.yaml up -d
curl --fail --silent --show-error https://sas-staging.example.org/health/live
curl --fail --silent --show-error https://sas-staging.example.org/health/ready
```

`/health/ready` must indicate database migrations are at the deployed release head. Test login, CSRF rejection, tenant isolation, finance corrections, exports and browser accessibility with synthetic records before any data cutover.

## Shared Caddy routing example (central ingress, not a SaS container)

Adapt the single **host-wide** Caddyfile entry after all three dashboard routes are planned. Keep the internal worker/callback endpoints **unpublished**:

```caddyfile
sas-staging.example.org {
    encode zstd gzip
    @sas_api path /v1/* /health/live /health/ready
    handle @sas_api {
        reverse_proxy sas-api:8001
    }
    handle {
        reverse_proxy sas-web:3000
    }
    header {
        X-Content-Type-Options "nosniff"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}
```

For stable upstream names, assign `sas-api` and `sas-web` as **network aliases** on `emlen_ingress` to their respective services. Only the central Caddy container should bind the VPS's 80/443 ports. If HTTPS routing or hostname resolution fails, stop rather than bypass Next.js origin validation or PostgreSQL TLS.

## Data migration, backup and rollback gates

1. Inventory the existing source DB, data volume, migration head, retention obligations, sender integrations and authoritative record counts before selecting a cutover window.
2. Keep sending disabled throughout a staging rehearsal. Obtain an encrypted, access-restricted source backup and restore to a NEW, empty recovery database. Independently verify tenant and ledger integrity using `app.restored_staging_audit` with its documented safety guards.
3. Record restore duration, RPO/RTO targets, checksums, encryption custody and approval evidence privately. **Do not** call a synthetic CI restore a proven disaster-recovery process.
4. Perform a staging UAT and security signoff. For production cutover, freeze writes on the source, take a final verified backup, apply forward migrations once, check exact row/ledger counts and readiness, then switch DNS/ingress.
5. Roll back compatible **application images** if a release fails. Do not blindly downgrade financial-schema migrations or restore an old backup over live writes. Maintain a named rollback operator and an incident plan.
6. Enable WhatsApp sending only in a separate, explicitly approved change after consent, opt-out, provider callbacks and deduplication have been tested. Nothing in this guide grants that approval.

**Status:** This document and Compose topology prepare an isolated staging candidate; the shared Caddy deployment, live VPS tests, source-data inventory, backup drill, production authorization, and domain/SSL verification remain outstanding.
