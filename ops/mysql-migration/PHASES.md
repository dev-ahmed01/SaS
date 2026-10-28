# Sponsor a Salah — phased PostgreSQL to InterServer MySQL 8.4 migration

Status: Phase 1 safeguards and partial Phase 2 MySQL 8.4 integration tests. NOT READY for real-data transfer or hosting cutover.

## What we have established

- Existing CRM main branch uses PostgreSQL and must remain unchanged until a controlled release.
- The proposed destination is a new isolated MySQL 8.4 database on the existing InterServer DirectAdmin account. The user's phpMyAdmin screen shows MySQL Community Server 8.4.11.
- Current Node.js and Python application selectors are visible, but compatible Node 22, FastAPI ASGI hosting, process restarts and cron schedules are NOT independently verified.
- The authoritative source PostgreSQL database, version, live records, backup, tenant and permissions are NOT yet identified. Do not assume the developer/demo database is the source of truth.
- The DirectAdmin account hosts many existing databases. Do not migrate into or alter any existing database.

## Phase 1: inventory and protection (in progress)

1. Identify authoritative PostgreSQL source with an authorized operator; never place DB secrets, recipient data or ledgers in GitHub, tickets or chat.
2. Inventory every table, row count, field type, UUID identity, foreign key, index and trigger, along with financial and WhatsApp/OTP lifecycle records.
3. Confirm a consistent encrypted PostgreSQL backup can be independently restored and audited.
4. Establish MySQL differences and preserve PostgreSQL source behavior.
5. Implement an offline reconciliation contract and no-data/network tests.

Exit gate: source identified; migration mapping complete; initial safeguards and CI passing. No live database writes.

## Phase 2: backend and MySQL schema

1. Add a pinned MySQL driver and explicit, guarded configuration while retaining production PostgreSQL behavior.
2. Build a separate MySQL 8.4 schema/migration path with proper foreign keys, unique constraints, validation checks, JSON, UUID, datetime and collation handling.
3. Re-create one-current-promoter-per-prospect as a MySQL-enforced rule, keeping historical assignments.
4. Re-create the ₹250 financial-tier guard and all other database-enforced constraints.
5. Test concurrent payment, OTP, duplicate-mobile, audit logging and Saasyto campaign claim safety with real MySQL 8.4 test transactions.

Exit gate: no-network MySQL integration tests, migration-drift check, restore and concurrency tests pass. No real data.

## Phase 2 progress — MySQL 8.4 trial branch (not production enabled)

Implemented:
- `app/mysql_trial_schema.py` creates a detached MySQL-specific candidate schema and refuses to touch any database except an empty `sas_mysql_trial_*` database on loopback with `APP_ENV=test` and `SAS_MYSQL_TRIAL_ONLY=1`. This is NOT connected to application production configuration or Alembic.
- MySQL 8.4 InnoDB with explicit `utf8mb4_0900_as_cs` collation on candidate tables.
- MySQL generated nullable column + unique index enforces **one current promoter assignment** while allowing historical ended assignments; the PostgreSQL partial-index definition remains unchanged.
- MySQL INSERT/UPDATE triggers enforce the current ₹250 manual collection rule for NEW/changed records. They deliberately do not impose a whole-table CHECK that would invalidate historical below-tier receipts. Real-data import must install these guards only *after* controlled historical import, followed by integrity audit.
- `requirements-mysql-trial.txt` installs a pinned test-only PyMySQL driver.
- CI now provisions an isolated MySQL 8.4 service, creates the full trial schema, checks constraints with synthetic transactions, and exercises a basic FastAPI Admin/Prospect/Promoter journey.

Verified with GitHub's disposable MySQL 8.4 service: schema creation, promoter/financial guards and the real Admin/Prospect/Promoter API smoke test passed. The latest added tests must pass the CI run for this commit.

Additional validation:
- Real FastAPI MySQL trial routes now cover Admin login, Prospect and Promoter creation, one collection with request-id retry and duplicate-reference rejection, invalid amount rejection, collection reversal with request-id retry, one-time payout with retry and duplicate-reference rejection. All fixture contacts are synthetic and no sender is enabled.
- Reconciliation manifest contract advanced to `sas-migration-manifest-v2` to distinguish independent bank credits from manually attested collections. This prevents false failures when verified bank credits legitimately have no manual collection.
- Additional MySQL integration covers synthetic OTP activation consumed once (no live OTP sends), stored OTP lifecycle timestamps, and two simultaneous InnoDB sessions selecting disjoint queued recipients under `SKIP LOCKED`. This is not yet a full multi-worker Saasyto dispatcher test.
- MySQL candidate `DATETIME(6)` now preserves PostgreSQL-style microseconds. SQLAlchemy's generic `DATETIME` would otherwise silently truncate fractional seconds, so later import code must explicitly normalize every historical timezone-aware timestamp to UTC before insert.
- `make_trial_engine` configures per-connection UTC and `READ COMMITTED` isolation (matching PostgreSQL's usual statement visibility rather than MySQL's default repeatable read); these settings are enforced by the guarded trial preflight and tested in MySQL CI.
- Remaining unverified: high-throughput multi-process payment/message concurrency, arbitrary imported histories, full communication/OTP state parity and authoritative-source export/restore.

Still blocked:
- Production/staging config **rejects** MySQL by design.
- Existing PostgreSQL Alembic chain is **not** being applied to MySQL.
- No source-to-target export/import, historical reconstruction or record-level digest generator exists.
- Full UTC timestamp import normalization, InnoDB fairness under real multi-worker dispatch, and all other message/OTP/payment lifecycle edge cases still require MySQL tests.
- No actual DirectAdmin deployment, source database backup, donor record import, or sender activation occurred.

## Phase 3: repeatable data-copy rehearsal

1. Work from an isolated restored PostgreSQL snapshot, not an unverified live export.
2. Write a resumable, idempotent source-to-target copier, preserving exact IDs, relationships, monetary integers, historical states and timestamp meanings.
3. Rehearse into a freshly provisioned MySQL database with messaging/scheduled jobs disabled.
4. Compare row counts on every table; canonical keyed HMAC-SHA256 content digests; integer-paise gross/net aggregates; reversals, payouts, tenant relationships, audit history, and reminder/campaign statuses.
5. Confirm no silent record omission or newly generated IDs.

Exit gate: repeatable evidence of exact transfer and an independent restore. Equal row counts alone are NOT enough.

## Phase 4: isolated InterServer staging

1. Confirm Node 22 and compatible Next.js application manager.
2. Confirm FastAPI ASGI hosting or an approved separate backend. Python Selector advertises WSGI and cannot be assumed to run FastAPI unchanged.
3. Confirm cron/worker scheduling and process restart behavior even if a prior manual WhatsApp send worked.
4. Use a fresh CRM subdomain, dedicated MySQL schema/user, HTTPS and synthetic/no-send test configuration.
5. Test authentication, all modules, imports/exports, database recovery, backup restore, and worker interruption.

Exit gate: verified complete app operation on the actual hosting plan.

## Phase 5: controlled cutover

1. Stop writes and dispatch on the source and settle in-flight transactions or mark uncertain states.
2. Take a final consistent encrypted PostgreSQL snapshot. Never delete it.
3. Load into a clean destination and re-run all table/content/ledger/relationship comparisons.
4. Route the CRM subdomain only after approval and keep source PostgreSQL available read-only for rollback.
5. Monitor finance and communication states and document recovery for any writes made to the new target.

Exit gate: data independently reconciled, business acceptance, monitored backups and documented cutover/rollback owner.

## Findings from code (not assumptions about live data)

| Area | Existing behavior | Required migration work |
| --- | --- | --- |
| Production config | app/config.py only accepts postgresql+psycopg in staging/production | Add explicitly reviewed MySQL config, driver and TLS/location policy |
| Partial unique index | app/models.py uses PostgreSQL/SQLite index WHERE ended_at IS NULL for current promoter assignment | MySQL has no equivalent partial index; copying the index unchanged forbids historical reassignment, omitting it risks two concurrent promoters. Redesign constraint first |
| Contribution policy | Migration 0013 explicitly rejects unsupported database dialects | Implement/test MySQL-enforced ₹250 rule |
| CRM migrations | 0014, 0015, 0018 branch between PostgreSQL/SQLite | Port full schema path and FK/trigger/default behavior to MySQL |
| Campaign queue | Committed one-time claims and organization locks, SKIP LOCKED | Test InnoDB isolation, overlapping claims and crash recovery under real concurrency |
| Data formats | UUID, JSON and timezone-aware datetimes | Define canonical UTC timestamp, UUID and JSON mapping; test MySQL collation and uniqueness differences |
| Restore audit | app/restored_staging_audit.py assumes PostgreSQL public schema | Create separate MySQL integrity audit |

## Offline contract added in Phase 1

File: apps/api/app/mysql_migration_reconcile.py
Tests: apps/api/tests/test_mysql_migration_reconcile.py

No database connection, message sender or data export exists in this code. It only compares separately generated aggregate manifests. Both source and destination must share the SAME snapshot ID and exact sets of ORM tables for table_counts and table_hmac_sha256. Financial aggregates compare gross/net manual collections, separate net manual-attested credits, gross/net all verified credits (including bank reconciliations), and gross payout payments. A bank-reconciled credit is **not** required to have a corresponding manual collection. Only manual-attested net credit and manual-collection net are required to balance. Referential, tenant, current-assignment and ledger-balance integrity checks must all pass.

A future exporter must create keyed HMAC-SHA256 over canonical ordered records, using a secret key outside GitHub and logs. Raw hashes of individual donor fields are not acceptable. Do not invent or manually set integrity flags to true.

After reviewed manifest exporters exist, an operator can run the module on private local files with flags --source and --target. Even if the comparison passes, its result always contains cutover_authorized=false. This is one validation gate, NOT proof of deployment readiness.

## Absolute restrictions

- No modification to existing DirectAdmin databases, source production DB, WhatsApp flags or deployed CRM.
- No customer financial or contact data in source control, test fixtures, CI artifacts or support tickets.
- No real-data copy until full source backup and independent restore are verified.
- No production cutover without verified transaction isolation, schema constraints, exact data comparison and rollback.
