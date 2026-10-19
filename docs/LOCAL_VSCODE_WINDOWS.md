# SaS — Windows VS Code localhost quick start

Use this procedure only on your own Windows computer with **synthetic/local data**. The optional short-password demo login is **disabled by default** and cannot be enabled in staging/production.

## 1. Requirements

Install [Git](https://git-scm.com/download/win), [Python 3.12](https://www.python.org/downloads/), [Node.js 22 LTS or newer](https://nodejs.org/), [Docker Desktop](https://www.docker.com/products/docker-desktop/) and [VS Code](https://code.visualstudio.com/). Start Docker Desktop first. In VS Code select **Terminal → New Terminal** (PowerShell).

```powershell
git clone https://github.com/dev-ahmed01/SaS.git
cd SaS
git switch main
py -3.12 --version
node --version
docker compose version
```

If the repository is already cloned, open that folder in VS Code and run `git pull origin main` rather than cloning again.

## 2. Configure local-only PostgreSQL and API secrets

These commands create only an ignored `apps/api/.env`; the password below is for **local PostgreSQL**, not the Admin login. Don't copy these defaults to any real environment.

```powershell
$authSecret = py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"
$upiSecret = py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"
@"
APP_ENV=development
DATABASE_URL=postgresql+psycopg://sas_dev:change-me-for-local-only@127.0.0.1:5432/sas_dev
AUTH_SECRET=$authSecret
UPI_MATCH_SECRET=$upiSecret
LOCAL_DEMO_LOGIN_ENABLED=true
MESSAGING_DELIVERY_ENABLED=false
MESSAGING_SENDER_APPROVED=false
PROMOTER_DISCLOSURE_APPROVED=false
"@ | Set-Content -Path apps\api\.env -Encoding utf8

docker compose up -d db
docker compose ps
```

Docker Compose creates the `sas_dev` database using the repository's local-only default password. If an older `sas_postgres` volume already exists with a different password, reconcile its connection settings rather than deleting real data. **Never run `docker compose down -v` on a database with records you need.**

## 3. Backend, migrations and local Admin setup — Terminal 1

```powershell
cd apps\api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.local_demo_admin
```

At the interactive prompts, enter **your chosen local-only Admin demo password** twice. The password is not visible as you type and is never committed to GitHub. The installer creates username `Admin` (backed internally by a local invalid-domain email) and refuses to overwrite any already-provisioned Admin.

Start the backend in the same terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000/health/ready](http://127.0.0.1:8000/health/ready). The JSON should be `{"status":"ready"}`.

## 4. Frontend — Terminal 2

Open a **second** terminal from the `SaS` folder:

```powershell
cd apps\web
@"
NEXT_PUBLIC_LOCAL_DEMO_LOGIN_ENABLED=true
API_INTERNAL_URL=http://127.0.0.1:8000
"@ | Set-Content -Path .env.local -Encoding utf8
npm ci
npm run dev
```

Open [http://localhost:3000/login](http://localhost:3000/login). On localhost the login field accepts `Admin` as username; type the password entered in Terminal 1.

## Optional: populate 100 synthetic CRM prospects

**Only on a disposable local demo database**, after creating your Admin and running migrations. The seed command refuses staging/production and requires local demo mode with messaging disabled.

From `C:\Users\Admin\Desktop\SaS\apps\api`:

```powershell
# Read-only preview; no records are added.
.\.venv\Scripts\python.exe -m app.seed_local_crm

# Only when you confirm the local database contains NO real donor information:
.\.venv\Scripts\python.exe -m app.seed_local_crm --apply --confirm-synthetic-only
```

It creates **100 clearly named Demo prospects, 10 Demo promoters and 20 planned Demo payouts**, with sample cities, ₹250-tier sponsorship commitments, 75 Active and 25 Inactive CRM statuses, inactivity reasons, optional promoter assignments, and example pipeline stages if none have been configured. Existing stage definitions are retained. This does **not** create received collections, outgoing payout disbursements, verified credits, WhatsApp consent or outbox messages; it changes local dashboard commitment metrics. Rerunning the same command does not duplicate the synthetic people.

Seed data is never loaded automatically at startup or added to production. Back up your existing database if it contains anything important. Do not share the seeded database as genuine financial data.

## 5. Troubleshooting

- `py -3.12` not found: install Python 3.12 with its Windows launcher and reopen VS Code.
- `docker compose` fails: start Docker Desktop and ensure port 5432 is not used by another PostgreSQL service.
- `Admin already provisioned`: the database is not empty. The safe bootstrap refuses to replace the existing Admin or overwrite data. Do not delete the volume to resolve this unless you have explicitly confirmed it contains no important records.
- `503 Sign-in unavailable`: check backend /health/ready, API secrets in `apps/api/.env` and `API_INTERNAL_URL` in `apps/web/.env.local`.
- `401 Invalid email or password`: ensure `LOCAL_DEMO_LOGIN_ENABLED=true`, restart the backend after changing it, and verify the password you entered during setup.
- `Email address` rather than `Email or username`: restart `npm run dev` after changing `NEXT_PUBLIC_LOCAL_DEMO_LOGIN_ENABLED`.
- No real WhatsApp messages can be sent from this development configuration.

## 6. Stop safely

In both terminals press **Ctrl+C**. From the repository root, run `docker compose stop db`. This **keeps** the PostgreSQL data volume intact.

Production login continues to require a valid email, Argon2 authentication and passwords of at least 12 characters. The development alias and short-password exception must never be used for real Foundation operations.
