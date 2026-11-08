# One Contabo HTTPS ingress for SaS, WE and AE

**Staging use only.** The three application repositories remain independently built, released and recovered. This directory is the **one common proxy** and should be deployed separately from each application's private Docker stack. The proxy uses only the external shared Docker network and cannot access their private database/media networks.

The three source configs live at:
- SaS: `ops/staging/compose.shared-ingress.yaml` (this repository)
- WE: `dev-ahmed01/Dashboard-WE/compose.shared-ingress.yaml`
- AE: `dev-ahmed01/AE-dashboard/compose.shared-ingress.yaml`

## Before exposing any domain

- Confirm Docker Engine + Compose, patched Ubuntu, firewall, SSH key authentication, ingress access policy, valid DNS A records for each staging hostname, and administrator-approved domains. Do **not** copy personal donor/student records or enable outbound WhatsApp/SMTP.
- The three apps need separate private DB volumes, object-storage buckets and secrets; never share these by mistake.
- Staging admin access should be protected with an identity-aware gateway (such as an approved Cloudflare Access policy) **before** making HTTPS available to testers. A hard-to-guess URL is not authentication.
- The proxy will bind public 80 and 443; it cannot run beside another container that already owns those ports. Check `docker ps` before starting and avoid replacing an existing live site's reverse proxy.
- Create the shared ingress network **once**, not on each application restart: `docker network create emlen_ingress`.
- Use `docker compose --env-file ops/shared-vps/.env -f ops/shared-vps/compose.yaml config --quiet` to validate this proxy stack.

## Initial staging setup

From the SaS repo root:

```bash
cp ops/shared-vps/.env.example ops/shared-vps/.env
chmod 600 ops/shared-vps/.env
# Edit every value in ops/shared-vps/.env to your real staging DNS names.
# Never commit this file.

docker network create emlen_ingress

docker compose --env-file ops/shared-vps/.env \
  -f ops/shared-vps/compose.yaml config --quiet
```

First prepare each project using its own migration guide. The SaS staging host in `ops/staging/.env` must match `SAS_HOST`; WE `WE_STAGING_HOST` must equal `WE_HOST`; AE `AE_STAGING_HOST` must equal `AE_HOST`. Run each project's **one-off schema migration** and require healthy services before routing browsers to them. All components use distinct Compose `name:` values, preventing volume/container collision.

Once network aliases, DNS and all three private test stacks are ready, start the **only** Caddy process:

```bash
docker compose --env-file ops/shared-vps/.env \
  -f ops/shared-vps/compose.yaml up -d

docker compose --env-file ops/shared-vps/.env \
  -f ops/shared-vps/compose.yaml ps
```

Validate all three certs and endpoints externally using their **actual configured hostname**. For SaS, `https://$SAS_HOST/health/ready`; WE and AE, `https://$WE_HOST/api/health/ready` and `https://$AE_HOST/api/health/ready`. Do not disable certificate verification to pass the check. Test protected login, logout, permissions, same-origin mutations, SEO noindex, backups and restore isolation.

## Release gates

- GitHub main protections, independent PR review and pinned reproducible builds.
- Real VPS security posture, host resource/disk monitoring, separate encrypted off-host DB and media backups.
- Successfully witnessed restore into separate empty systems, recorded RPO/RTO, incident owner and rollback dry run.
- App-specific finance/privacy/data-consent signoffs and documented launch authorization.
- Email verification, Meta/Saasyto/OTP, production domains, canonical SEO and customer data migrate **only** in separately approved cutovers.

No secrets, backups or customer records are stored by this proxy repo. The example hostnames and admin email are **not** working production settings. If a previous Caddy/Nginx site already handles 80/443, integrate these route definitions into it rather than running a second gateway.
