# Sponsor a Salah — production readiness and controlled launch

**Release candidate (20 October 2026). Status: NO-GO for live Foundation records or public donor operations.**
A passing GitHub CI pipeline is a *source verification*, not a tested hosting deployment,
an authorization to collect real donor information, or approval to send WhatsApp messages.

This is the Foundation's existing Phase 13 approval process with technical controls drawn
from [Google SRE launch reviews](https://sre.google/sre-book/launch-checklist/),
[NIST SP 800-218 SSDF](https://csrc.nist.gov/pubs/sp/800/218/final) and
[OWASP ASVS 5.0](https://github.com/OWASP/ASVS/tree/master/5.0).
These external guides are engineering references, not Foundation approvals.

## Gate record — do not mark external work completed without evidence

| Gate | Current state | Operator/verifier |
| --- | --- | --- |
| Source quality, backend/frontend integration, synthetic PostgreSQL and browser tests | CI verified at the specific PR SHA only; reverify final SHA after merge | Engineering |
| Production dependency scan | CI now audits Python packages and production npm dependencies; confirm the latest green results | Engineering/security |
| Protected main branch | **BLOCKED**: no live ruleset; GitHub owner must enable independent review and required checks | Repository owner |
| Deployment inventory | **NOT DEPLOYED**: no identifiable SaS Vercel/Render/Railway service; connected Supabase project inactive | Operations |
| Staging infrastructure + HTTPS + isolated database | **BLOCKED**: must be provisioned and tested with synthetic data | Operations |
| Foundation finance policy and payout approval | **BLOCKED**: confirm payment-reference evidence, optional external reference policy, reversals, outgoing proof and authority | Foundation finance |
| Consent/retention and beneficiary privacy | **BLOCKED**: approve opt-in wording, retention/deletion access and donor data transfers | Foundation |
| Backups and isolated production-like restore | **BLOCKED**: synthetic CI restore is NOT evidence of a real encrypted backup with measured RPO/RTO | Operations |
| Messaging/scheduling | **OFF**: require sender ownership, Meta templates, delivery callback, STOP/re-consent, private scheduler and promoter disclosure permission | Messaging owner |
| Monitoring/incident response | **BLOCKED**: assign incident owner, test alert routing, emergency stop and rollback | Operations |
| Responsive UAT and release acceptance | Automated browser tests are green; independent stakeholder staging acceptance pending | Foundation |
| Dated approval and rollback owner | **BLOCKED** | Foundation signatory |

The project has a separate fail-closed documentary gate,
`python -m app.release_gate`, that checks metadata only. Never fabricate or commit
filled approval forms.

## Ordered technical procedure (staging with synthetic data only)

1. **Freeze a release candidate.** Use protected `main` after reviewed CI. Record
   the exact 40-character SHA, Actions links, dependencies, test skips and any
   known issues. Open `docs/PHASE_13_PRODUCTION.md` and Issue #13.
2. **Verify code and dependencies.** CI must pass Ruff, pytest, PostgreSQL migration
   checks, synthetic restore, Next typecheck/build, desktop/mobile Playwright,
   `npm audit --omit=dev --audit-level=high` and `pip-audit -r requirements.txt`.
   Review *all* critical/high vulnerability reports, not just the exit code.
3. **Protect repository.** Enable the checked-in `ops/github/main-ruleset.json`
   by the authorized repo owner using `app.repository_ruleset`. Require an
   independent review, up-to-date `backend` and `frontend` checks, no bypass,
   no force push and no main deletion. Verify the live GitHub ruleset.
4. **Provision separate staging resources.** Use fresh, dedicated Next.js (Vercel),
   FastAPI (Render or equivalent) and managed PostgreSQL services with no production
   donors, no imported bank data, no public DB access and no outbound jobs.
   Confirm legal/data protection and hosting-region decisions with the Foundation.
   No new paid service should be provisioned before authorization for billing.
5. **Configure backend** (server-only, in provider secrets dashboard):
   - `APP_ENV=staging`, `LOCAL_DEMO_LOGIN_ENABLED=false`
   - `DATABASE_URL=postgresql+psycopg://...?...sslmode=require` (use
     `verify-full` with provider CA whenever supported; **never** disable TLS).
   - unique `AUTH_SECRET` and independent `UPI_MATCH_SECRET` each 32+ characters;
     the latter must survive session-key rotation and **must not** be regenerated
     during routine deployments.
   - `MESSAGING_DELIVERY_ENABLED=false`,
     `MESSAGING_SENDER_APPROVED=false`, `PROMOTER_DISCLOSURE_APPROVED=false`.
     No scheduler/worker or public messaging runner credentials in staging.
   - Database role: least privilege. Separate migration credentials and runtime
     credentials if supported. Securely store secrets; never share with frontend.
6. **Apply migrations exactly once** with an authorized one-off release job:
   `cd apps/api && python -m alembic upgrade head && python -m alembic check`.
   Take/verify a backup first for an existing environment. Do **not** casually
   run destructive downgrades. Production API start command (Render Python service):
   `python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
   No `--reload`. Use `/health/live` for process health and `/health/ready`
   for DB + migration readiness; 503 is a stop sign.
7. **Configure Next.js** (root: `apps/web`; Node 22; `npm ci`; `npm run build`).
   Set `APP_ENV=staging`, `API_INTERNAL_URL=https://<staging-api-host>` and
   `APP_PUBLIC_ORIGIN=https://<exact-staging-web-host>` as **server-side**
   variables. The backend must be reachable over TLS from the actual Next.js
   host, not just your laptop. Distinguish API URL from DB URL; never configure
   `NEXT_PUBLIC_` variables containing keys. Prefer preview protection.
   Use staging-specific origins; do not reuse production sessions or databases.
8. **Verify the deployed systems over HTTPS.** Observe `/health/ready`, verify
   release SHA and migration revision, test cookie `Secure`, `HttpOnly`, session
   expiry, CSRF rejection, forged Origin failure, admin login throttling,
   cross-organization denial and no public unauthenticated donor API data.
   Confirm response security headers, no caching of sensitive page/data responses,
   and that direct production DB access from the Internet is blocked.
9. **Run staged acceptance with synthetic data.** Register sponsor and promoter;
   assign/unassign; record a ₹250-tier payment without and with a reference;
   verify duplicate reference rejection, exact sponsor/month allocation, IST
   boundaries, fully/part-paid, audited reversal and corrected ledger; run
   recurring/one-time payout attestations; confirm new/active/inactive lifecycle.
   Save/cancel communications, consent opt-in/opt-out and dry-run recipients.
   Confirm **zero provider messages and zero real money movement**.
10. **Backup and restore DRILL.** Obtain an encrypted backup of the **staging**
    database, restore to a NEW EMPTY isolated target with all outbound jobs
    disabled, check migration head and finance/tenant hashes. Measure and
    record business-selected RPO/RTO, retention, encryption custody and operator
    approvals. Never restore to an existing live database.
11. **Monitoring and rollback.** Assign named owner and pager/email recipient;
    test alerts for 5xx, failed readiness, login abuse, DB saturation, migration
    mismatch, corrections and message status unknown. Dry-run fast rollback of
    the Next/API binaries while preserving financial tables. Disable message
    worker immediately on incidents, and never replay ambiguous provider
    attempts. Confirm logs omit passwords, tokens and donor PII.
12. **Governance & authorization.** Finance and Foundation privacy owners must
    approve evidence standards and data collection; Operations approves backup,
    disaster recovery and response; Foundation signatory dates UAT acceptance.
    WhatsApp delivery is a **separate** launch requiring real sender/template,
    STOP, callback and cost sign-offs. Only after all required evidence is
    stored outside Git may production receive real donor data.

## Go/no-go rules

- **Local or isolated private staging (synthetic data):** proceed only after
  configuration, migration, TLS and endpoint checks; no real data or messaging.
- **Production domain with real sponsors/collections:** **NO-GO** until every
  required gate above has verifiable Foundation evidence and operations ownership.
- **WhatsApp live sending:** separate **NO-GO** until Meta/Pabbly end-to-end
  approvals and callback/STOP tests are independently witnessed.
- CI has no access to the future hosting network, real payer data, bank receipts
  or Meta credentials and therefore cannot certify those systems.
- On deployment failure, revoke the release, keep messaging disabled, inspect
  migrations/DB ownership, redeploy prior compatible binaries, preserve finance
  history and record the incident.

**Known implementation boundaries**: Single Admin role; recorded incoming/outgoing
money is manually attested after external transfer; application neither reconciles
bank balances automatically nor executes transfers. Documentation must not imply
otherwise.
