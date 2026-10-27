# Restore local CRM after a failed legacy identity migration

Use only on the verified **local** Docker/PostgreSQL `sas_dev` database
when Alembic reports **0021_unique_prospect_mobile** cannot proceed because
a seeded `First Prospect` has the same mobile as one sponsor with a promoter.

The migration must **not** be changed to auto-merge donor identities. It
refuses conflicting numbers on purpose. Once the unique database index exists,
new duplicates are rejected even when submitted concurrently; application
validation also checks normalized mobile, including archived prospects.

## One-command repair (PowerShell)

First stop the local API on port 8001 and any scheduled/WhatsApp workers.
Ensure all required repository updates have been pulled from `main`.
Then open PowerShell in the SaS repository root:

```powershell
.\scripts\Repair-SaSLegacyDuplicate.ps1
```

This command:
1. Confirms the API is stopped and the configured database really is the
   loopback-only `sas_dev` in development mode.
2. Starts the existing local PostgreSQL Docker service without recreating
   volumes, takes a `pg_dump -Fc` archive, validates it with `pg_restore -l`,
   and copies the dated backup to your Desktop.
3. Checks the exact unique duplicate group, inactive seed identity,
   unverified WhatsApp status, one old sponsorship-rate record, one stage
   transition, **zero** other prospect/recipient references, and exactly one
   promoter assignment on the surviving Prospect.
4. Displays the two records, last four mobile digits, links and backup name.
   Requires the operator to confirm **REMOVE FIRST PROSPECT**.
   If any check or confirmation fails, the SQL transaction is rolled back,
   the remaining sponsor and existing history are untouched, and migrations
   are not attempted.
5. Preserves the removed test row and two test links in a new immutable audit
   snapshot. Deletes precisely those three test rows, verifying that the
   kept Prospect and promoter association are unchanged.
6. Applies all pending Alembic revisions and prints the current head.

The repair has deliberately **no generic delete mode**, no network messaging,
and no override for a different database, business contact or linked payment.

If the script refuses, **do not edit constraints, delete rows manually, or
run `docker compose down -v`**. Inspect the error and resolve that specific
collision before running the migrations again.

After success, restart:
```powershell
cd apps\api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Check `http://127.0.0.1:8001/health/ready` for HTTP 200 before logging
in to the web frontend on port 3002. Local readiness now checks Alembic
heads just as staging/production already did.

## Guardrails

- This repair is destructive **only to the disposable seeded test identity**
  and its two validated test links. The operator must independently confirm
  the seed identity is disposable.
- Audited financial records and communication/OTP history cannot be
  auto-merged or deleted. Unexpected links cause STOP.
- Earlier backup files remain available; this script always makes a new
  verified backup itself and never overwrites previous ones.
- This procedure does not operate on staging, production, or any remote DB.
