# Phase 13 — Synthetic PostgreSQL Recovery Drill

**CI implementation — not a production restore or a Foundation acceptance sign-off.**

The recovery test uses only GitHub's ephemeral PostgreSQL 16 service, synthetic sponsor/receipt data and a short-lived, newly created database with the `sas_restore_ci_` prefix. It does not contact messaging providers, create real records or execute any payout.

## How the CI drill works

1. The backend job first migrates `sas_ci` to the current Alembic head and runs integrity tests.
2. The drill refuses to run unless `APP_ENV=test`, `SAS_SYNTHETIC_RESTORE_CI=1`, PostgreSQL/psycopg, database `sas_ci`, user `sas_ci`, host `127.0.0.1` or `localhost`, and port 5432 all match exactly. Query parameters or remote hosts are rejected.
3. It inserts an unmistakably synthetic organization and sponsor with a ₹500 commitment, two ₹250 manual collections, one audited reversal and an **unexecuted** payout plan. Organization messaging is disabled and consent is false.
4. It takes a real PostgreSQL 16 custom-format dump using the matching ephemeral Docker client, then restores into a newly created disposable database. Neither source nor target is staging or production.
5. It compares every restored public table's row count and row-content hash to its source, checks net credited amount (₹250 after reversal), validates the unexecuted payout plan and verifies automation is still disabled.
6. It deletes the backup with its temporary directory and drops the isolated database in a guarded cleanup. Output contains aggregate test flags, elapsed seconds and table counts, not donor names, phone numbers, transaction references or passwords.

The CI command is intentionally scoped:

```bash
# Only for the existing ephemeral sas_ci PostgreSQL service created by CI
APP_ENV=test SAS_SYNTHETIC_RESTORE_CI=1 \
DATABASE_URL='postgresql+psycopg://sas_ci:<CI-ONLY-PASSWORD>@127.0.0.1:5432/sas_ci' \
python -m app.synthetic_restore_ci
```

**Never change the hard-coded scope to make the test work against a live database.** The drill creates a new database and can never be used as the real Foundation restore operator. Do not publish CI backup files as artifacts.

## What remains unproven

This is a *synthetic backup/restore verification of the code and PostgreSQL tooling only*. It is not evidence of an encrypted production backup, retention policy, selected Recovery Point Objective (RPO), measured business Recovery Time Objective (RTO), production PostgreSQL permissions, offsite recovery, privacy compliance or operational data correctness. CI elapsed time is not the business RTO.

A real Foundation staging recovery must be separately approved by the authorized operator and use a private source and a **verified empty, isolated target**, with outbound WhatsApp delivery and schedulers OFF, private backup storage, encrypted transport, redacted evidence, external witness and signed acceptance. A recovery must never be attempted against an existing production database. The actual procedure and release gates remain in [PHASE_13_PRODUCTION.md](PHASE_13_PRODUCTION.md), with all unapproved sign-offs recorded in [Issue #13](https://github.com/dev-ahmed01/SaS/issues/13).
