# Sponsor a Salah · CRM End-to-End QA and Business Rules

Test design: isolated synthetic datasets only. No production or existing demo
sponsor data is modified; live WhatsApp, Saasyto, Pabbly and OTP sending remain
disabled. Browser visibility in Chat mode is read-only; the interactive UI
journeys run in GitHub Actions against a synthetic backend.

## Coverage approach

Use positive, negative, boundary, integration, concurrency/data-integrity,
security and regression tests. Validate the same rules in **client**, **API**
and **database** layers as appropriate. Reference:
- OWASP WSTG Business Logic Data Validation:
  https://wstg.owasp.org/latest/4-Web_Application_Security_Testing/10-Business_Logic/01-Business_Logic_Data_Validation/
- OWASP ASVS 5.0:
  https://asvs.owasp.org/
- OWASP Access Controls:
  https://devguide.owasp.org/en/04-design/02-web-app-checklist/07-access-controls/
- E.164 numbering conventions:
  https://www.twilio.com/docs/api/errors/63107

## Core business-rule matrix

| Domain | Positive journey | Negative/boundary cases | Evidence |
| --- | --- | --- | --- |
| Identity | Two prospects can have the same full name but **different** normalized mobiles | Same mobile under same foundation, in edit, after archival, and concurrently; invalid national/Unicode digits | `test_crm_end_to_end_journeys.py`, `test_postgres_integration.py`, Playwright |
| Registration | Default New Inquiry, inactive CRM, never paid | Forged stage on create, forged payment status, missing/invalid fields, idempotency misuse | API tests and stage regression tests |
| Journey stages | Version-checked stage change from Prospect Details | Deleting assigned stage, stale version, cross-tenant stage | `test_prospect_pipeline_stages.py` |
| Promoters | Same display name with distinct numbers, reassignment with complete audit | Duplicate phone, assignment to inactive promoter, missing transfer target, stale data | API and Playwright |
| Collections | Admin-attested ₹250 multiples, current or valid historic period, one receipt | Inactive/archived/unknown sponsor, future date, ₹249.99/₹250.01, reused request or receipt reference | API and browser integration |
| Reversals | Mistaken receipt reversed once with retained audit | Wrong confirmation, duplicate reversal, duplicate request ID | API, accounting and browser |
| Payouts | One-step attested payment, independent of receipt amounts | Missing funds-attested flag, duplicate UTR, idempotency misuse, future payment | API and browser |
| Communications | Approved template/audience review, consent filtered by live state | Missing consent, opt-out, malformed campaign, stale approval, sending disabled by default | Messaging and Saasyto tests |
| Security | Admin session, CSRF, tenant isolation, unique DB constraints | Forged origin, unauthenticated access, optimistic version conflicts, invalid states | Security suite and CI |
| UX | Create/search/edit/archive/restore, responsive phone/desktop, clear errors | Duplicate-phone error explanation; invalid inputs; responsive flows | Playwright CI |

## Confirmed issues addressed by the October 25 hardening

1. **Phone collision (API and DB):** Prospect identities were not unique by
   mobile number within a Foundation. Enforce normalized E.164 with a unique
   `(organization_id, mobile_number)` index, including archived records.
   The display name is deliberately NOT unique.
2. **Creation-stage bypass:** API previously allowed a caller to set a pipeline
   stage on initial registration. The server now defaults to New Inquiry and
   requires a separate versioned edit to change stage.
3. **Race/conflict feedback:** Concurrency-safe index violation surfaces HTTP
   409, with a useful duplicate-mobile error rather than an unexplained 500.
4. **Phone number syntax:** Reject non-ASCII numeric characters rather than
   relying on Python's Unicode `\\d` matching.
5. **Browser testing realism:** Generate unique synthetic numbers per create
   journey; cover two identical names with different numbers, a third duplicate
   mobile attempt, and a readable UI error.
6. **Consent/address binding:** Editing a prospect or promoter to a new WhatsApp
   recipient address now automatically clears the legacy opt-in and appends an
   opted-out consent event. A new sender must obtain fresh documented permission
   for that number before any reminder or general campaign can send.

## Continued audit: live reminder eligibility across month boundaries (PR #48)

**Reproducible defect:** The general Communication audience, its Saasyto
approval/dispatch path and the unpaid promoter segment considered the CRM
`active` stage but did not consistently apply the **two completed IST months
without positive net credits** inactivity rule. With a stale materialized
lifecycle status, the same sponsor could be excluded by the dedicated Reminders
module yet remain eligible for a Communication reminder. Reversing the sole
payment could recreate that mismatch.

**Enforced invariant:** At Communication recipient review and Saasyto send
eligibility, recompute inactivity from tenant-scoped effective credits,
excluding reversed manual entries. Direct unpaid sponsor and consolidated
promoter audiences exclude inactive sponsors. An active but never-paid sponsor
is allowed only before two complete overdue months; an eligible partial
contribution reactivates promptly, while an append-only reversal removes that
activity. Recipient-address consent checks remain in force independently of
financial eligibility. No messaging transport is enabled by these changes.

**Synthetic regression** in `test_reminder_net_activity_qa.py`:

| Journey | Check | Expected |
| --- | --- | --- |
| No credit in two completed IST months | `/v1/communication/audience` reminder `all` and `unpaid` | Suppressed; cached lifecycle status cannot override the ledger |
| Active promoter assigned only that unpaid sponsor | Consolidated unpaid promoter preview | Zero eligible promoter recipients |
| Partial ₹250 credit against ₹500 commitment | Sponsor/promoter previews and native reminder module | Reactivated sponsor; eligible remainder of ₹250 |
| Reverse that credit | Same endpoints | Sponsor and promoter previews become ineligible again |
| 31 Oct 23:59 to 1 Nov 00:00 IST | Communication unpaid preview, no refresh operation | Turns ineligible exactly when the second missed month completes |

**CI skip/warning triage (from post-merge PR #47 evidence):** The 24
`test_postgres_integration.py` cases are skipped in the SQLite primary suite
only because their `DATABASE_URL` guard requires PostgreSQL; they execute in
the dedicated PostgreSQL CI step (24 passed). The browser suite's one skip is
the desktop half of a deliberately mobile-only layout case
(`test.skip(!isMobile)`), which runs on mobile. Ten backend warnings are
dependency / Alembic deprecations: one Starlette TestClient warning and nine
Alembic `path_separator` warnings, not failing assertions. Track these during
dependency upgrades rather than treating the skips as unrun database cases.

**Release boundary:** Verify the new PR's own backend/PostgreSQL/browser checks,
not just an earlier successful main run. Tests use disposable databases and
mock/no-send transport; real Saasyto approval and production rollout still
require the existing sender, webhook, privacy and staging sign-off gates.

## Continued audit: explicit opt-out must override native reminder checkboxes (PR #49)

**Reproduced rule mismatch in source:** The dedicated `/v1/reminders`
sponsor and promoter previews originally checked only legacy
`whatsapp_opt_in` flags and addresses. However, the Communication
module can record an explicit `opted_out` consent event independently
of that checkbox. Thus an opt-out could remain in a prepared reminder
recipient set, and `current_intent_eligible` could consider it eligible.

**Hardening:** Reuse the tenant-scoped shared consent decision engine in
native sponsor and consolidated promoter reminder previews. This applies the
latest explicit opt-out, address-level opt-out blocking and duplicate-address
suppression while retaining current payment, assignment and two-missed-month
eligibility checks. Prepared reminders must revalidate the same consent at
send-time; no transport is activated.

**Regression paths:** A sponsor opts out after an eligible batch is prepared
while the old WhatsApp checkbox remains checked; preview and intent
revalidation must both reject it. An active promoter with an eligible unpaid
sponsor opts out; the consolidated reminder must no longer count that promoter
or include their sponsor in a dispatchable summary. These cases run in
`test_reminders.py` using synthetic addresses, no actual messages.

## Continued QA: Promoter assignment classification across IST rollover (PR #50)

**Confirmed source mismatch:** the Promoters `/{promoter_id}/sponsors` endpoint
filtered `kind=prospects`/`kind=sponsors` by the stored
`Prospect.lifecycle_status` column and exposed that same stored value. The
Dashboard, Accounting and Prospect Details endpoints already recomputed
lifecycle from current IST date and *net* credit history. When stored lifecycle
had not been refreshed, the same prospect could appear in an incorrect
promoter tab with an incorrect status, even though reminders were properly
suppressed by the live accounting policy.

**Correction:** Preserve the approved two-table UI and the existing
`new` versus non-`new` grouping, but use the shared tenant-scoped,
read-only `_project_statuses` path before filtering. Apply pagination **after**
the projected filter, so `total`, pages and displayed statuses agree.
Join each sponsor with the assignment's organization ID to retain
tenant isolation. GET is strictly read-only: no version increment,
materialized state mutation or fabricated audit event.

**Synthetic regression** `test_promoter_live_lifecycle_qa.py`: same sponsor
at 31 Oct 23:59 IST versus 1 Nov 00:00 IST; a second sponsor with a
legitimate October payment despite a stale `new` cache; paginated
`kind=sponsors` count versus rows; no mutations during reads; and a
partial contribution followed by append-only reversal reflecting immediately
in the Promoters and Prospect Details views.

**Open architectural gate:** materialized `lifecycle_status` still requires
an authenticated status refresh endpoint; this PR fixes the outward-facing
Promoter list without silently scheduling an unapproved worker. Production
automation of materialization requires a private authenticated scheduler and
isolated staging validation. No provider sends or real donor data are touched.

## Continued QA: Reject no-op promoter reassignment requests (PR #51)

**Confirmed input-validation bypass:** a Promoter PATCH carrying only
`reassign_to_promoter_id` or `reassign_individually`, with no actual field
change, returned a successful unchanged profile **before** evaluating whether
reassignment was permitted. This was misleading: an Admin could believe
assignments had moved even though the transfer did not occur. A simultaneous
unchanged `is_active: true` had the same bypass.

**Correction:** validate incompatible bulk/individual selections and require
a genuine deactivation transition *before* the normal no-change return.
Without deactivation, reject with HTTP 422 and preserve the promoter,
current assignment, version and audit history. Ordinary unchanged non-transfer
edits remain valid no-ops.

**Regression:** a sponsor assigned to promoter A; attempt bulk, individual,
empty individual and unchanged-active transfer requests toward B. All must be
rejected without changes to either promoter or historical assignment count.
Test remains entirely synthetic and does not send any notifications.

## Parallel PostgreSQL invariants and early-flush conflict handling (PR #52)

The existing `test_postgres_integration.py` covered mostly **sequential**
duplicate attempts. These are not evidence of two concurrent database
connections competing over the same unique keys. New isolated PostgreSQL
tests use two threads with separate SQLAlchemy sessions and a start barrier,
plus a bounded PostgreSQL lock timeout. SQLite deliberately skips them.

**Scenarios** (all synthetic, disposable CI tenants):
- Simultaneous manual-attested credit, receipt and outbox writes using the
  same tenant/request/source reference: one atomic ledger entry wins, one
  transaction rolls back; no orphan verified credit or outbox intent.
- Simultaneous reversals of a single receipt using separate request IDs:
  exactly one immutable reversal exists, the original receipt remains and
  the net credit is zero.
- Simultaneous assignments of one sponsor to two promoters: exactly one
  active assignment survives the PostgreSQL partial unique index.
- Simultaneous *different-tenant* writes reusing the same synthetic request
  and receipt reference: both succeed independently, demonstrating that
  tenant-scoped uniqueness is not a globally shared restriction.

**API hardening:** Some collection and reassignment flows flushed ledger
rows before the final `commit()` exception handler. A unique-key collision
at those earlier flushes could therefore surface as an unhandled server
error instead of an explicit conflict. Early collection credit, receipt,
reversal and promoter assignment flushes now roll back and return HTTP 409.
One HTTP regression seeds an existing source-key conflict and asserts no
partial credit, collection or outbox records from the rejected request.

**Limit:** These exercises verify database uniqueness under simultaneous
transactions; they do not constitute a performance benchmark or an
end-to-end concurrent HTTP load test. The API's effective transaction
serialization and tenant access permissions still require staging review
before production launch. No real bank records or outbound messages are used.

## Migration and existing data

`0021_unique_prospect_mobile` runs a **read-only preflight** against all
prospect rows, including archived rows. If legacy duplicate phone groups exist,
the migration fails safely, reporting the count of affected groups without
printing phone numbers or changing identities.

Preflight with PostgreSQL, before deployment:

```sql
SELECT COUNT(*) AS duplicate_mobile_groups FROM (
    SELECT organization_id, mobile_number
    FROM prospects
    GROUP BY organization_id, mobile_number
    HAVING COUNT(*) > 1
) duplicates;
```

A nonzero result **requires an authorized manual review** of which records
represent the same person and their contribution, assignment and audit
histories. Do **not** blindly delete/merge prospects or rename numbers.
Once reconciled, back up the database and run `alembic upgrade head`.
Mobile numbers remain reserved if a prospect is archived: use Restore for
the original record.

## Release evidence and limitations

- Test run and job logs: record actual outcomes from the PR CI, not a claimed
  result from browsing a live data set.
- This is a targeted hardening sweep alongside the existing 200+ backend and
  90+ browser regression tests, **not** a guarantee of zero bugs.
- Performance/load tests, external provider deliveries and exhaustive
  penetration tests need a properly isolated staging environment.
- Never activate any live messaging flag to exercise synthetic journeys.
