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
