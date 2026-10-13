# Sponsor a Salah

**Emlen Foundation — Admin-only charity operations application.**

## Project state

Phases 01–11 have implementation branches with passing development CI but their stacked pull requests remain under review, not merged into `main`. Phase 12 adds the real-data, read-only dashboard and is undergoing verification. Phase 13 (production acceptance and deployment) is not complete. **This is not an operational payment or live WhatsApp service.**

Checkout `phase/12-live-dashboard` to inspect the complete development stack; `main` currently contains only the initial repository scaffold. Review [the implementation roadmap](docs/PHASES.md) and [locked UI requirements](docs/DESIGN_LOCK.md) before changes.

## Product boundaries

- Admin-only prospects, promoters, manual collections, full audited corrections, recurring/one-time payout obligations, reminders, settings and dashboard.
- Approved 13 October 2026: new sponsorship commitments are positive ₹250 increments (new organization default ₹250); any positive recorded contribution reactivates, and two completed IST months without net recorded contributions cause inactivity. Partial receipts are not restricted to ₹250 increments.
- The Foundation records receipts and outgoing payments **after funds have moved externally**. This application does **not** move money or independently verify bank transactions.
- Incoming payment acknowledgments and 5th/20th reminders are **prepared but not delivered** until Meta/Pabbly authorization, approved templates, consent, secret configuration, a private dispatcher and signed delivery callbacks have been tested. Provider acceptance is not delivery.
- Bank statement import is deferred by the Foundation. No mock donors, fake payment history or delivered-message fixtures are used in the live UI.
- Operational proof policy and promoter disclosure require Foundation approval before release. Read [decisions](docs/DECISIONS.md) and the appropriate phase documents.

## Stack

- `apps/web`: Next.js 15, TypeScript, server-side authenticated gateway, approved Bricolage Grotesque/Poppins sidebar UI.
- `apps/api`: Python 3.12, FastAPI, SQLAlchemy, Alembic and PostgreSQL, organization-scoped financial records and audit history.
- `.github/workflows/ci.yml`: Ruff, pytest, PostgreSQL migrations/integrity checks, Next.js production build and desktop/mobile Playwright.

## Local development (synthetic data only)

Requires Node.js 22+, Python 3.12+, PostgreSQL 16+ or Docker:

```bash
git switch phase/12-live-dashboard
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

**Release rule:** No production enablement or actual WhatsApp dispatch until all approved business policies, ordered PR integration, staging UAT, backup/restore, security, consent and provider checks pass. See `docs/PHASE_11_MESSAGING.md`, `docs/PHASE_12_DASHBOARD.md` and `docs/PHASES.md`.
