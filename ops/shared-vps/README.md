# Single HTTPS gateway for SaS first, WE and AE later

The gateway is a **single** Caddy container that owns TCP 80/443 on Contabo. The SaS private production stack is `ops/contabo/compose.production.yaml`; SaS staging has a separate stack under `ops/staging/`. Never run both stacks with the same public SaS hostname and routing alias without an explicit switch plan.

## SaS-only first deployment

```bash
cp ops/shared-vps/.env.example ops/shared-vps/.env
chmod 600 ops/shared-vps/.env
docker network inspect emlen_ingress >/dev/null 2>&1 || docker network create emlen_ingress
```

Edit the ignored private `.env` to set `ACME_EMAIL`, the **actual** SaS hostname matching the SaS stack's `SAS_HOST`, and the correct upstream aliases:

- **SaS production:** `SAS_API_UPSTREAM=sas-prod-api:8001`, `SAS_WEB_UPSTREAM=sas-prod-web:3000`
- **SaS synthetic staging:** `SAS_API_UPSTREAM=sas-api:8001`, `SAS_WEB_UPSTREAM=sas-web:3000`

The Caddy service exposes only HTTP/HTTPS, while DB/API/Next.js have no host-published ports. The Caddy network alias for the exact SaS hostname ensures the Next.js server can verify the same-origin HTTPS certificate without insecure localhost exceptions.

Only after SaS's private containers are healthy and DNS is correct:

```bash
docker compose --env-file ops/shared-vps/.env -f ops/shared-vps/compose.yaml config --quiet
docker compose --env-file ops/shared-vps/.env -f ops/shared-vps/compose.yaml up -d
```

Use `ops/contabo/DEPLOY.md` for the first production deployment, separate database restoration, backup encryption and approved WhatsApp activation. No source change alone authorizes live Foundation data.

## Add WE and AE without another 80/443 listener

The Caddyfile imports `ops/shared-vps/sites/*.caddy`. An empty import is explicitly supported by Caddy. Nothing is imported by default; the `other-dashboards.example` file is just a template. When the other dashboards have their own private databases, media buckets, healthy web containers and real DNS, copy only the approved WE/AE blocks into respective `.caddy` site files and provide `WE_HOST`/`AE_HOST` to the gateway's private environment. Use a staging-only `X-Robots-Tag: noindex`, identity-aware access policies and distinct application credentials.

**Preflight gates:** no other reverse proxy already owns 80/443; TLS and DNS work, only Caddy binds host ports, private data networks are isolated, GitHub release SHA/CI are recorded, encrypted offsite backups restore successfully, independent UAT is signed, and live sender permission remains an explicit separate change.
