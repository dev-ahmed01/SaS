# Sponsor a Salah

**Emlen Foundation — internal charity operations web application.**

> **Phase 01 / 13 — foundation.** This branch delivers a working application scaffold, a first database migration, API health probes, tests and CI. Login, payment reconciliation, WhatsApp delivery and live module functionality are **not** implemented. Nothing in this branch should be deployed as a live financial system.

## Architecture

- `apps/web`: Next.js + TypeScript; shared visual tokens for the approved light/green design.
- `apps/api`: FastAPI + SQLAlchemy + Alembic; PostgreSQL in production.
- `docs`: authoritative product decisions, architecture, phase acceptance gates and outstanding integrations.
- `.github/workflows/ci.yml`: backend tests/schema migration and frontend checks.

## Run locally

Prerequisites: Node.js 22+, Python 3.12+, PostgreSQL 16+ (or Docker).

```bash
cp apps/api/.env.example apps/api/.env
# Set DATABASE_URL for local PostgreSQL, then:
docker compose up -d db
cd apps/api
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd apps/web
npm install
npm run dev
```

Open `http://localhost:3000`; API liveness: `http://localhost:8000/health/live`; database readiness: `http://localhost:8000/health/ready`.

**Local-only bootstrap:** Phase 03 will introduce Admin provisioning and secure login. No default credentials are installed. `npm install` currently resolves from pinned package versions; commit an npm lockfile before a production deployment to enable `npm ci` and dependency reproducibility.

## Test

```bash
cd apps/api && pytest -q
cd apps/api && ruff check .
cd apps/web && npm run typecheck && npm run build
```

## Workflow

Use feature branches and PRs; verify CI before merging. Store secrets in the deployment provider, never in Git. Deploy only after the remaining security, financial and communication phases pass review and UAT. See `docs/PHASES.md`.
