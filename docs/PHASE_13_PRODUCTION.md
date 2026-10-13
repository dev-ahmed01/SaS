# Phase 13 — Production release and Foundation acceptance

**Current status: NOT RELEASED.** Passing development CI means source and synthetic fixtures were verified, not that a real Foundation account is operational. This document is the mandatory release gate. No donor imports, payments, actual WhatsApp sends or payout execution are authorized by this document.

## Release prerequisites (all require recorded evidence)

| Gate | Required evidence | Owner/approval | Status |
| --- | --- | --- | --- |
| Canonical business policy | Sign-off for New sponsor reminder permissions, evidence standards and billing exceptions; sponsorship multiples and inactivity are approved | Foundation finance lead | **Partially resolved — sponsorship and inactivity approved 13 Oct 2026** |
| Review/integration | Full stack integrated atomically via PR #17, accepted CI on actual `main` SHA `e48b3155`; independent production review and branch protections still required | Tech reviewer | **Code integrated; protected `main` pending** |
| Authentication/tenancy | Login abuse cases from distinct client networks; Admin CSRF/session/proxy tests; inaccessible cross-organization records | Security reviewer | **Staging pending** |
| Finance | Approved manual receipt evidence standards, reversals and outgoing payout proof; synthetic month-end and historical corrections | Foundation finance lead | **Pending** |
| Environment | Production/staging separate PostgreSQL, web, API, DNS, HTTPS and managed secrets | Operations owner | **Not provisioned/verified here** |
| Data lifecycle | Retention schedule, restricted imports, sponsor/promoter consent, audited archives, restoration-period dues invariant | Foundation privacy lead | **Pending** |
| Recovery | Encrypted backups, restore into isolated database, migration/health smoke, selected and measured RPO/RTO | Operations owner | **Not yet witnessed** |
| WhatsApp | Official Meta Business sender, templates, cost authorization, Pabbly request validation, **genuine** status callbacks and STOP re-consent | Foundation messaging owner | **Off / unconfigured** |
| Monitoring | Error, auth abuse, provider unknown/failed state, payment corrections and outage alerting with incident owner | Operations owner | **Pending** |
| UI review | Approved light sidebar hierarchy, Bricolage/Poppins, responsive/accessible screens; empty/errors with no fabricated financials | Foundation stakeholder | **Pending stakeholder UAT** |
| Final approval | Dated written Foundation approval and named rollback operator | Foundation authorized signatory | **Not granted** |

**Approved on 13 October 2026:** new recurring sponsorship commitments AND new incoming Admin-recorded contributions are positive multiples of ₹250 and newly provisioned organizations default to ₹250. Existing effective-dated rates do not change. Two completed IST months with zero net recorded receipt activity cause inactivity. Any positive net recorded receipt, including valid ₹250-tier entries for an earlier billing month, reactivates; credit reversals negate that activity. Other operational and messaging policies still need explicit approval. The payment method remains Admin-attested manual entry, NOT a bank importer. Until sign-off, postpone decisions that would alter sponsor lifecycle, obligations, reminders or launch data.

## Deploy topology and control boundaries

- **Next.js web**: public browser endpoint, same-origin BFF, server-only `API_INTERNAL_URL`, exact `APP_PUBLIC_ORIGIN`; no public browser access to backend secrets.
- **FastAPI API**: HTTPS behind restricted ingress. `/internal/messaging/*` is authorized with independent runner or callback credentials and should additionally be network-filtered. Prefer a private web→API link and deny direct public database access.
- **PostgreSQL**: encrypted-at-rest managed service, TLS connection, explicit backup/restore privileges, minimal runtime DB role, tested migration operator credentials and separate environments.
- **Pabbly + Meta WhatsApp**: private recipient consent and template restrictions; actual provider event ID and signed callback needed to claim sent/delivered. A Pabbly HTTP 2xx is **accepted**, not delivery.
- **Scheduler**: not yet provisioned. Only approved private POST to `/internal/messaging/dispatch` with runner secret; do not put runner tokens in Next.js or public schedulers. Worker's start must be after the future activation cutoff and only after finance freshness approval.

The proposed vendors (Vercel web, Render API, managed PostgreSQL) are design suggestions, not verified resources. Confirm provider-region/data transfer and pricing with the Foundation. Do not confuse the public application origin with internal API origin.

## Preflight: no live data

1. Build and run reproducibly from the **approved integrated `main` SHA**, never `phase/*` alone. Pin the SHA in the release record.
2. Run `python -m ruff check .`, `python -m pytest -q`, `python -m alembic upgrade head`, `python -m alembic check`, and PostgreSQL integrity tests; keep separate staging DB credentials.
3. Run `npm ci`, `npm test`, `npm run typecheck`, `npm run build`, and authenticated desktop/mobile Playwright against the **staging FastAPI + PostgreSQL** stack. Record exact Actions run URLs and failures/skips.
4. Independently run secret scans, lockfile audit and supply-chain review. Do not assume `npm ci --no-audit` verifies vulnerability status; CI-only Playwright dependencies also require review.
5. Validate `APP_ENV=staging` rejects real messaging enabled, `MESSAGING_DELIVERY_ENABLED=false`, organization `automation_enabled=false`, and `PROMOTER_DISCLOSURE_APPROVED=false`. Confirm no automation runner or Meta account is connected in staging unless separately approved with synthetic recipients.
6. Confirm PostgreSQL client TLS, HTTPS cookies, correct proxy/origin handling, rate-limit separation, expiration/logout, failed-CSRF rejection, secure audit events, log PII masking and cross-tenant isolation.
7. Review actual migration lineage 0001 through 0010 **plus any subsequently merged revisions**. Do not rewrite or squash applied production revisions.

## Release evidence dossier (offline, does not authorize launch)

The release candidate includes `python -m app.release_gate`, a fail-closed parser for Foundation-controlled sign-off metadata. The [blank evidence template](RELEASE_EVIDENCE_TEMPLATE.json) intentionally has every gate unapproved. **Never commit filled evidence, donor details, private URLs with tokens, real keys or actual beneficiary records.** Store the completed file in a Foundation-controlled encrypted audit location.

From `apps/api`, after installing the backend dependencies:

```bash
python -m app.release_gate /secure/private-release-dossier.json --sha <approved-40-character-main-sha>
```

A nonzero exit indicates missing or invalid metadata. An exit code of zero means the *form* has all 12 attestation fields, not that signatories, hosted systems, Meta/Pabbly integrations, legal consents, deployment configuration or backup restoration were independently verified. The program never makes network requests, sends a message, runs migrations or deploys. The operator must still witness every external gate and explicitly authorize an independently controlled release.

**Repository observation 13 October 2026:** `main` was not protected when inspected after merging PR #17. Enable required `backend`/`frontend` status checks, independent code review, no-force-push and branch deletion restrictions in GitHub repository settings, then collect actual evidence. The code in this PR cannot change hosted repository protections.

## Backups, restore drill and cutover

**Do not execute restoration against an existing production database.** A restore drill must use an isolated, newly created target with permissions and outbound messaging disabled.

- Select approved RPO/RTO and retention period; record encryption/key custodians, automated schedule, offsite location and tested restore procedure. These values remain **unapproved**, not assumed.
- Generate a PostgreSQL consistent backup under an authorized maintenance identity (example structure: `pg_dump -Fc --no-owner --no-acl -f staging-snapshot.dump "$STAGING_DATABASE_URL"`; protect the file and never commit it).
- Restore to an **empty disposable** PostgreSQL database: `pg_restore --no-owner --no-acl -d "$DISPOSABLE_RESTORE_URL" staging-snapshot.dump`. Before running, verify both URLs are isolated from production and the app/worker are not pointed at the disposable target.
- On the isolated restore: check migration head, row counts per tenant, immutable manual collections and reversal exclusion, payout plan/payment separation, unique reference constraints, audit trail and read-only Dashboard totals. Ensure no job can dispatch message intents from copied data.
- Record command outcomes, timestamp, storage/retention evidence, checksum, version, RPO/RTO observed, access restrictions, reviewer sign-off and cleanup. Retest after breaking schema changes or provider changes.
- Cutover requires a reversible release/feature-flag plan; freeze financial writes only during an approved maintenance window and verify both source and target financial ledgers before reopening.
- Rollback executable code without blindly downgrading financial schema. Never discard collected financial records or receipt corrections to match an old binary.

## Finance UAT with synthetic records

Use isolated synthetic sponsor/promoter identities and distinct cash/UPI transaction references. Test each against ledger AND six-month Dashboard:

- New sponsor without a payment; ₹250-tier contributions, full and excess payments (reject below-minimum and off-tier entries); payment month effective rate (never assume current sponsor rate matches past period); two monthly boundaries including year-end IST.
- Duplicate click/reference across changed payment methods; late entry with distinct `received_on`, target month and `created_at`; past before-enrollment/future-month rejection.
- Full audited reversal, including correct net outstanding and unsent confirmation suppression; verify previous original credit still exists.
- Archive and restore across calendar months with **no retrospective dues for paused periods**; the unresolved historical-interval issue must be fixed and proven before launch.
- Recurring payout scheduled/paused/resumed/closed, one-time planned vs actually attested paid, early one-time disbursement blocked, unique outgoing reference, wrong-tenant rejection and plan/outgoing distinction.
- Exact sponsor New/Active/Inactive transitions under the approved October 13 rule, with valid ₹250-tier late-allocated receipt reactivation and reversal suppression.
- Empty Foundation with zero real activity must show zero, never fictitious donations/notifications.

## Messaging UAT with explicit opt-in test phone only

Require written Meta sender and approved template authorization before any provider-side attempt. Audit recipient opt-in source, change/revocation timing and data minimization. Simulate or verify under controlled real-provider UAT:

1. Manual receipt saves its single immutable credit, audit event and optional **pending** confirmation. No message is marked delivered from the database insert.
2. HMAC-authenticated Pabbly requests, deduplication and genuine signed Meta status callback. Verify provider `accepted` versus `sent` versus `delivered`, non-replay/downgrade.
3. Reversal and opt-out immediately before dispatch suppress sends. Never retry `unknown` timeouts without human investigation.
4. Only qualified unpaid sponsors on configured 5th IST; one aggregate promoter follow-up on configured 20th, only after specific donor disclosure approval. Recheck current assignments and net finance.
5. Old queued messages before activation cutoff cannot be released, neither by the scheduler nor by re-enabling the organization.
6. Production automation toggle is audited, Admin+CSRF guarded and explicitly confirmed. Test emergency disable during an incident and that no further claims are created.
7. Document inbound STOP/unsubscribe/re-opt-in mapping with Meta/Pabbly; until verified, DO NOT authorize launch. Confirm message costs and contact/privacy retention.

## Monitoring, response and ownership

Run separate alerts for API readiness/latency, auth failure/rate-limit spikes, PostgreSQL connections/migration mismatch, old `claimed` messages, provider `unknown`/failed callbacks, signed callback failures and stale manual finance entry periods. Logs must include correlation IDs without raw UPI, full reference, donor phone or secrets.

On suspicious donor messages or financial discrepancy: disable organization automation, disable `MESSAGING_DELIVERY_ENABLED` through secured deployment control, stop scheduler, preserve audit/event evidence, communicate to the Foundation incident owner, reconcile from original records and record the postmortem. Never re-drive unknown delivery attempts blindly.

## Acceptance record — fill only with witnessed facts

| Field | Evidence to capture |
| --- | --- |
| Approved release SHA + integrated PRs | ____ |
| All CI workflow links + browsers/migration outputs | ____ |
| Resolved policy decisions with Foundation signatory | ____ |
| Staging environment, HTTPS/DB isolation, test date | ____ |
| Restore drill output, tested RPO/RTO, reviewer | ____ |
| Synthetic finance UAT reconciliation document | ____ |
| Sender/template/consent approval and opt-out test | ____ |
| Signed real-provider callback and recipient UAT receipt | ____ |
| UI accessibility, locked layout approval | ____ |
| Incident owner and rollback/kill-switch tested | ____ |
| Production sign-off date, owner, approval reference | ____ |

**No row may be pre-filled with simulated success.** Until every applicable gate has evidence, the release state is **BLOCKED**.