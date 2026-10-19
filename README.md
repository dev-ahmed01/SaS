# Sponsor a Salah

**Emlen Foundation — Admin-only charity operations application.**

## Release-readiness status (October 2026)

**Not approved for live Foundation records.** Read
[the production readiness checklist](docs/PRODUCTION_READINESS_CHECKLIST.md).
Hosted environments require TLS-enabled PostgreSQL, correct migrated database
schema, an explicit HTTPS API and public web origin, and guarded messaging.
Next.js was updated to the security-patched 15.5.27 series. CI adds production
dependency audits. A real staging deployment, protected main, witnessed
backup restoration, monitoring and written Foundation approval are still
separate release gates. Do not use synthetic CI data as live-deployment proof.

## Project state

**Phases 01–13 are integrated into `main`** through [PR #17](https://github.com/dev-ahmed01/SaS/pull/17), merge commit `e48b3155e4e7bbda65e00f2df07d13cb251b74fe`. [Post-merge CI](https://github.com/dev-ahmed01/SaS/actions/runs/38414100426) passed backend and frontend jobs. The phase branch history and reviews remain available. **The application is source-integrated but NOT production-released**: no provider WhatsApp delivery is enabled, no real payout is executed by the software, and Foundation acceptance is outstanding.

Use `main` for current development, [the integration record](docs/INTEGRATION_REVIEW.md) for provenance, [the roadmap](docs/PHASES.md) and [locked UI requirements](docs/DESIGN_LOCK.md).

## Product boundaries

- Admin-only prospects, promoters, manual collections, full audited corrections, recurring/one-time payout obligations, reminders, settings and dashboard.
- Approved 13 October 2026: new sponsorship commitments are positive ₹250 increments (new organization default ₹250); any valid positive recorded contribution reactivates, and two completed IST months without net recorded contributions cause inactivity. Sub-₹250 and non-multiple receipts are rejected at entry; historical entries are not repriced or deleted.
- The Foundation records receipts and outgoing payments **after funds have moved externally**. This application does **not** move money or independently verify bank transactions.
- Incoming payment acknowledgments and 5th/20th reminders are **prepared but not delivered** until Meta/Pabbly authorization, approved templates, consent, secret configuration, a private dispatcher and signed delivery callbacks have been tested. Provider acceptance is not delivery.
- Bank statement import is deferred by the Foundation. No mock donors, fake payment history or delivered-message fixtures are used in the live UI.
- Operational proof policy and promoter disclosure require Foundation approval before release. Read [decisions](docs/DECISIONS.md) and the appropriate phase documents.

## Stack

- `apps/web`: Next.js 15, TypeScript, server-side authenticated gateway, approved Bricolage Grotesque/Poppins sidebar UI.
- `apps/api`: Python 3.12, FastAPI, SQLAlchemy, Alembic and PostgreSQL, organization-scoped financial records and audit history.
- `.github/workflows/ci.yml`: Ruff, pytest, PostgreSQL migrations/integrity checks, Next.js production build and desktop/mobile Playwright.

## Windows VS Code — local Admin demonstration

For an exact local username of `Admin`, use the explicit development-only bootstrap in [Windows VS Code localhost guide](docs/LOCAL_VSCODE_WINDOWS.md). The demo mode must be enabled in an ignored local `.env` file, uses a loopback-only PostgreSQL database, prompts for your chosen password instead of committing it, and never changes production authentication. Normal `bootstrap_admin` still requires 12+ character passwords and an email address. Do not reuse demo credentials with real Foundation records.

## Local development (synthetic data only)

Requires Node.js 22+, Python 3.12+, PostgreSQL 16+ or Docker:

```bash
git switch main
cp apps/api/.env.example apps/api/.env
# Set local DATABASE_URL and fresh local secrets in apps/api/.env; never commit it.
docker compose up -d db
cd apps/api
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.bootstrap_admin
uvicorn app.main:app --reload --port 8000
```

Set `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ORGANIZATION` and optionally `BOOTSTRAP_AMOUNT_PAISE` before running `bootstrap_admin`; it prompts for the password. The Windows equivalent activation path is `.venv\\Scripts\\Activate.ps1`.

From a second terminal:

```bash
cd apps/web
npm ci
npm run dev
```

Browse `http://localhost:3000`. Test with `python -m ruff check .`, `python -m pytest -q` from `apps/api`, and `npm test && npm run typecheck && npm run build` from `apps/web`. CI additionally exercises the PostgreSQL migrations and authenticated browser suite.

**New Phase 13 operations:** [strict `main` protection and staging recovery audit](docs/PHASE_13_MAIN_PROTECTION_AND_STAGING.md), [manual release-governance workflow](.github/workflows/release-governance.yml), and [synthetic PostgreSQL restore](docs/PHASE_13_RECOVERY_DRILL.md). The GitHub owner must activate branch protection separately; an external Foundation staging backup/restore remains unverified.

**Release rule:** Code integration does not authorize production. Main branch protection, approved financial proof policy, staging UAT, real backup restoration, security, consent, opt-out, sender/template and provider callback checks remain mandatory. [Phase 13 production gates](docs/PHASE_13_PRODUCTION.md) and [Issue #13](https://github.com/dev-ahmed01/SaS/issues/13) track these separately.

A fail-closed **offline documentary check** is available after real approval records exist: copy `docs/RELEASE_EVIDENCE_TEMPLATE.json` to a secure, untracked location, fill all 12 gates with genuine evidence references, and run `python -m app.release_gate /secure/release-evidence.json --sha <40-character-release-commit>` from `apps/api`. Passing validates metadata completeness **only**; it does not independently verify a provider, configure branch protection, deploy software or authorize WhatsApp messages.
