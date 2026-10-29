# Sponsor a Salah — Pre-InterServer Rule and Integration Audit
Date: 29 October 2026. Branch: feat/interserver-mysql-phased-migration-20261029. PR: #101 (draft, unmerged).

**Decision: NO-GO for live migration/deployment until the blockers below are cleared.** This is a source-code and isolated-test audit, not a review of the real Foundation PostgreSQL database. Existing InterServer databases were not accessed.

## 1. Complete mapped database inventory: 35 tables

| Domain | Tables | Required data-preservation rule |
|---|---|---|
| Organization and Admin | organizations, admin_users, organization_settings | Keep tenant IDs, credentials hashes, INR/IST policy, disabled automation defaults |
| Access and audit | audit_events, admin_sessions, admin_login_attempts | Preserve access/audit chronology, JSON and security session history |
| Prospects | prospects, sponsor_otp_challenges | Preserve unique phone, status and version, OTP hash/attempts/expiry and sent/unconfirmed state |
| Prospect history | prospect_followups, prospect_stage_definitions, prospect_stage_transitions, prospect_archive_intervals, prospect_upi_ids | Keep follow-ups, stage names/IDs, archive periods and keyed UPI identifiers |
| Promoters | promoters, promoter_assignments | Keep historic ended assignments; maximum one current assignment per prospect |
| Incoming finance | sponsorship_rates, verified_credits, manual_collections, manual_collection_reversals | Keep effective rates, bank versus manual source, exact paise, duplicate keys, reversible audit history |
| Receipts/outbox | message_outbox | Preserve one intent per collection/event and suppressed/awaiting outcomes |
| Payouts | payout_plans, payout_plan_terms, payout_payments | Keep recurring/one-off policy, uniquely attested payment reference, request, month |
| Campaign configuration | communication_templates, communication_campaigns, communication_rules | Keep templates, campaign snapshots, explicit approvals and currently inactive automation definitions |
| Saasyto | saasyto_campaign_runs, saasyto_campaign_recipients | Keep one run per campaign and durable one-claim-per-recipient status, including UNKNOWN |
| Consent/previews | communication_consent_events, communication_preparations, communication_recipient_snapshots | Keep opt-ins, opt-outs and evidence, historical audience review |
| Reminders | reminder_batches, reminder_intents | Keep one monthly batch per type and contact, unpaid grouping and scheduled IST day |
| Legacy messaging | message_dispatches, message_delivery_events | Keep separate Pabbly dispatch and authenticated callback history; never confuse with Saasyto receipts |

Every table must be copied with original UUIDs, foreign keys, tenant IDs, timestamps/offsets, JSON, finance and suppression data. Equal row counts alone are not proof of success.

## 2. CRM and accounting policy audit

| Rule | Current code | Outcome |
|---|---|---|
| Prospect registration | May register before paying. Starts CRM Inactive and contribution lifecycle New. Phone unique within organization, idempotent request ID. | Existing code + tests |
| New commitment amount | ₹250 increments, ₹250 to ₹1 crore, stored as integer paise. | Existing code + tests |
| Historical finance | Old rates and historical below-tier contributions are not rewritten by the new ₹250 rule. | PostgreSQL design; MySQL import still blocked |
| Month/timezone | INR, Asia/Kolkata billing months; receipt date differs from allocation month; effective-dated sponsorship rate. | Existing code; future MySQL-aware timestamps need work |
| Inactivity | Two consecutive completed months with zero positive net credited activity -> Inactive. New positive recorded credit can reactivate, even when allocated to an older billing month. | Existing code + tests |
| Archived sponsors | Non-obligated archive months must not be back-billed; retain historical payments. | Existing code + tests |
| Collections | Active CRM sponsor only, no future or pre-registration payments, source-backed verified credit, unique request/reference, same-transaction outbox. | Trial MySQL API tested |
| Reversals | One reversal per collection, original retained, idempotent request, effective credits exclude reversed manual credit. | Trial MySQL API tested |
| Payouts | Admin-attested records, not an actual bank transfer; unique request/reference/recurring period. | Trial MySQL API tested |
| Promoters | Historical reassignments preserved; at most one active promoter per prospect. | MySQL generated-column unique index trial tested |
| OTP | Four digits, two-minute expiry, 60-second cooldown, max five daily issues and five verification attempts; success consumes once, reactivation needs reason. | Trial MySQL activation/replay tested |
| Permission | CRM Active and OTP verification DO NOT automatically create general marketing consent. Latest evidenced opt-out and address-level revocation wins. | Implemented; verify policy with stakeholder |
| Monthly reminders | Sponsor 5th IST if unpaid/eligible; promoter combined per promoter on 20th; re-evaluate live balances and permissions. | Preparation exists, automatic transport issue below |
| Campaigns | Review recipients, review expires after 15 minutes, explicit human approval, max 10,000 recipients, sending revalidates live consent. | Existing code + tests |
| Deletion and audit | Account history and foreign-key dependencies restrict deletion; stage changes and financial operations audited. | Existing code + tests |

There are TWO distinct sponsor states: CRM activation stage (active/inactive) and contribution-derived lifecycle (new/active/inactive). These are not interchangeable.

## 3. Saasyto integration audit

| Area | Verified from source code | Unverified or blocking |
|---|---|---|
| API send | Fixed HTTPS endpoint: https://web.saasyto.com/api/send. JSON fields number, type=text, message, instance_id, access_token. Five-second timeout, no redirects/proxy, default-off flags. | Public canonical endpoint/response documentation not found; obtain vendor contract |
| Outcomes | Gateway accepted_unverified / rejected / unknown. HTTP 2xx never counts as recipient delivery. Unknown/timeouts are not blindly retried. | No authenticated Saasyto delivery/read webhook contract; CRM read and delivered counts currently null |
| Queue | Durable pre-send claim, max 10,000 campaign recipients, 90-second default gap, rolling quota, 429 postponement, late consent checks. | Actual provider per-instance/API quota and no-ban guarantee unverified |
| Worker | Private production-only process requires delivery/sender/worker approval; local pilot is separate. | Long-lived process/restart/cron capabilities on DirectAdmin untested |
| Crash recovery | Internal runner already reconciles stale claims to UNKNOWN after 15 minutes; production private worker was missing that call. | Fixed in this branch, pending all CI |
| OTP route | Saasyto OTP or separately configured Meta OTP, selected prospect phone only, unconfirmed provider delivery does not validate OTP. | Need production sender setup, provider reply semantics and protected process logs |
| Campaign controls | Recipient check + Admin approval before send. Communication automation rules display active=false; definitions are NOT autonomous senders. | Must not turn on automatic publication without approval |
| 5th/20th automation | Updated on this migration branch: the legacy Pabbly worker/callback routes were removed, and a separately approved 5th/20th IST scheduler prepares Saasyto campaign runs. Production activation and worker behavior remain unverified. | Single Saasyto transport now implemented on branch; needs CI, worker/staging proof and sign-off before activation. Historical Pabbly dispatch records remain read-only. |
| Scale | At 90 seconds/attempt, 10,000 messages need at least 250 hours (~10.4 days), excluding outages. | Not a same-day 10k broadcast guarantee |

Saasyto public product marketing: https://saasyto.com/whatsapp-personal/ advertises unlimited plans, API integration and scheduling, but states no platform can guarantee protection from WhatsApp bans. A separate official product guide at https://saasyto.com/product/saasyto-personal-whatsapp-subscription/ recommends 90–120 seconds between messages for its **dashboard campaign** workflow, and an official blog at https://saasyto.com/send-bulk-broadcast-whatsapp-messages-in-2024/ advertises webhooks for incoming/outgoing/disconnection events. Neither is a published contract for this CRM's particular direct-send response fields, webhook signing, daily API throughput or delivery statuses. Do not use another provider's API docs as if they were Saasyto.

## 4. InterServer migration blockers

| ID | Severity | Finding and release gate |
|---|---|---|
| DB-01 | BLOCKER | Application config still rejects MySQL staging/production. Implement guarded MySQL production connection and TLS/version controls before deployment. |
| DB-02 | BLOCKER | Alembic 0001–0024 has PostgreSQL/SQLite-specific DDL. Build and drift-test versioned MySQL migrations, not only detached trial metadata. |
| DB-03 | BLOCKER | The synthetic MySQL schema installs ₹250 INSERT triggers before the copy; historic below-tier receipts will fail. Design isolated historical import, independent ledger audit and enforcement of new-write rule after import. |
| DB-04 | BLOCKER | MySQL DATETIME(6) preserves precision, NOT timezone offsets. Trial copy normalizes historical aware values, but future API writes (e.g. IST scheduled campaign planned_for) still need centralized UTC conversion. |
| DB-05 | BLOCKER | Authoritative Foundation PostgreSQL source, immutable backup, controlled access and independently verified restore are not identified. |
| DB-06 | BLOCKER | Trial copier is single-transaction synthetic localhost only and is not a restartable production importer. Need abort/recovery, all 35 table parity and independent ledger/tenant checks on a restored source. |
| HOST-01 | BLOCKER | DirectAdmin Node.js/Python setup screens do not establish Node 22 SSR, FastAPI ASGI, process stability, cron execution, memory/process limits or backup restore. Test isolated site on exact plan. |
| WA-01 | BLOCKER | Endpoint-specific Saasyto reply, idempotency, quotas and authenticated delivery webhooks are not verified by public product information. Obtain documented contract or owner-supervised integration evidence. |
| WA-02 | BLOCKER | Pabbly runtime removed on the branch. Saasyto monthly reminder preparation, consent revalidation and one-attempt queue are integrated but remain default-off pending real staging validation. Define one audited sender and ensure no duplicate delivery. |
| QA-01 | HIGH | CI MySQL 8.4 service uses a newer patch build than target screenshot's MySQL 8.4.11. Verify that specific target version before cutover. |
| QA-02 | HIGH | Preserve secrets necessary to match stored UPI/phone hashes, OTP hashes, session and signature state, or use an explicit safe rotation process. Never place secrets into GitHub. |
| QA-03 | HIGH | Historic dataset may contain old statuses, unusual JSON/timestamps, financial reversals and missing values absent from synthetic fixtures; test full real-history restore and reconciliation. |
| WA-03 | HIGH | Stakeholder request that all Active contacts get messages may conflict with code's evidence-based consent/opt-out rules. Obtain documented permission policy; do not bypass opt-outs. |
| WA-04 | HIGH | Rate limit and 90-second gap make 10,000 attempted contacts take at least 10.4 days. Get approved throughput/cadence from provider and stakeholder. |

## Implementation update — isolated compatibility work (no real data)

- All 59 ORM `DateTime(timezone=True)` columns now use `UTCInstant`, a PostgreSQL-compatible type that converts incoming IST/offset-aware datetimes to UTC on MySQL and returns UTC-aware datetimes. MySQL physically stores `DATETIME(6)`, preserving microseconds. The integer-paise `Date` billing calendar remains unchanged. PostgreSQL and SQLite bind/result handling is intentionally preserved; comprehensive CI verifies existing regressions.
- The copy-only MySQL trial can now provision an **empty test schema without the new-only ₹250 triggers**, copy older valid source financial history (including an explicitly seeded ₹125 historic receipt and corresponding credit) in a verified all-or-nothing data transaction, and **reinstall the triggers only after the verified copy commits**. The test then rejects modifying that historical receipt into a new invalid amount. Because MySQL trigger DDL implicitly commits, this is a **two-phase rehearsal**, not a production cutover or independently restartable importer.
- `MYSQL_STAGING_TRIAL_ENABLED` is an explicit opt-in **only** for `APP_ENV=staging`, `mysql+pymysql` and a `127.0.0.1:3306/sas_mysql_trial_*` disposable database. It refuses all outbound sender/OTP flags. The API engine runs `READ COMMITTED` and UTC sessions and checks schema table parity, MySQL 8.4 version, installed ₹250 guards and foreign key checks before allowing requests. **Production MySQL remains rejected.**
- These changes unblock more rigorous isolated integration testing but do not clear DB-01/02/05/06, HOST-01 or WA-01/02. A versioned production MySQL schema, authoritative backup/restore, full real-history reconciliation, worker/runtime proof, and a single approved reminder transport are still required. Do not deploy this staging trial to existing InterServer databases.

## 5. Verified tests and remaining test matrix

Already tested with synthetic data: PostgreSQL-to-MySQL all-table copy; per-table canonical keyed HMAC and count match; rollback on deliberate content corruption; destination-not-empty refusal; current/historical promoter uniqueness; new collection denomination; Admin/Prospect/Promoter API; collection duplicate/idempotency and reversal; one-time payout duplicate/idempotency; OTP single use; two disjoint locked queue claims; UTC session and microseconds. The new Saasyto worker crash recovery test must be green at latest commit.

Still required: exact InterServer MySQL patch; full old financial history with below-tier receipts, all tables represented and linked; versioned migration; offset-aware future MySQL writes; full per-record and tenant financial source audit; save/restore/retry interrupted transfer; real worker race, DB disconnect and provider 429; provider delivery/seen semantics; 5th/20th end-to-end sender and restart behavior; actual DirectAdmin staging.

## Release decision

**NO-GO** if any donor/contact/finance/audit/message row is missing, if a permission rule is weakened, if a historical record must be dropped, if recipient delivery is invented from gateway acceptance, if the production app/worker cannot restart, or if backup restore is unproven.

Only after a fully verified backup-derived rehearsal, exact accounting/record parity, vendor/hosting acceptance tests, chosen reminder sender and rollback plan should a controlled write freeze and InterServer cutover be considered. No real database transfer or live WhatsApp activation is authorized by this audit.


## Saasyto-only implementation update (29 October 2026)

- Pabbly send/callback code and configuration are removed on this branch, as are the old frontend delivery-status proxy and its Pabbly metrics. Existing historical database tables/rows are retained as read-only evidence; they are not reinterpreted as Saasyto receipts.
- The sole active campaign sender is the Saasyto private worker. A new separately gated monthly scheduler prepares Sponsor reminders on the configured 5th IST and one consolidated Promoter reminder on the configured 20th IST. Per-recipient messages are recomputed from live balances and consent before the worker calls Saasyto.
- Unique monthly reminder batch constraints plus deterministic campaign request IDs prevent duplicate schedules; already attempted legacy reminders cannot send through Saasyto again.
- Previously queued reminders expire when the IST day passes. Actual provider delivery/read callbacks remain unverified and are not inferred from HTTP acceptance.
- Payment collection confirmation outbox records are retained, but an automatic Saasyto receipt confirmation/re-send flow has **not** been approved or implemented. The manual resend endpoint now returns a safe unavailable response, rather than invoking the deleted Pabbly worker.
- See SAASYTO_ONLY_TRANSPORT.md for configuration gates, safety requirements, and current exclusions. Release still NO-GO pending full CI, versioned MySQL production migrations, authoritative backup/restore and InterServer worker/runtime tests.
