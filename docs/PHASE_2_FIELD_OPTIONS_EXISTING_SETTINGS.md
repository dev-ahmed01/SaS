# Sponsor a Salah — Phase 2 Field Options implementation plan

**Placement:** inside the existing Settings page (`apps/web/components/admin-settings-form.tsx`).
**Do not** introduce a new sidebar item, route, or "Settings module". Extend the current
"Organisation Settings" screen with a compact **Field Options** section; preserve
Team Access below it and its existing owner/other-role permission boundaries.

## UX contract

- Owner views configurable groups as compact horizontal headings / accordions:
  **Payout purpose** (first enabled group), **City** (optional future group).
- A group contains a searchable, reorderable list of options. Every option has an
  immutable code/ID, human-readable label, active status, and order.
- One inline Add option field. Option rows have Edit label and Deactivate/Reactivate
  actions with confirmation and conflict feedback; historical options cannot be
  hard deleted while referenced.
- New outgoing payment and recurring payout forms use the same **Purpose**
  combobox, populated from active choices. No arbitrary free text on normal
  new records after successful migration. Existing values remain visible and
  reportable even if their choice is later inactive.
- While option loading fails, do not fall back silently to arbitrary free text.
  Show an inline retry. Owner can maintain options in Settings; other roles
  have read-only access and approved role-based editing in Payouts.
- Standard button hierarchy: primary Save, secondary Add/Edit/Export, danger
  Deactivate/Reverse, consistent 42–44 px targets, no floating links.

## Backend design (PostgreSQL)

- Add `organization_field_options` with:
  `id` UUID, `organization_id` UUID FK, `field_key` bounded enum
  (`payout_purpose`, optionally `city`), `code` unique within org+field,
  `label`, `is_active`, `sort_order`, `version`, `created_at`, `updated_at`.
- Use a new Alembic migration with an index over
  (organization_id, field_key, is_active, sort_order) and a casefolded duplicate
  label guard. Do not rewrite immutable payout ledger events.
- Seed a small owner-reviewable initial purpose set (e.g. Rent, Utilities,
  Maintenance, Salary, Vendor payment, Reimbursement, Other) only as
  **configuration defaults** on new organizations. For existing organizations,
  add a non-destructive migration path: import distinct historical purpose
  labels after owner approval, so old reports remain accurate.
- Reuse existing authentication, session/CSRF, organization authorization,
  version optimistic concurrency and audit events.
- New owner-protected settings endpoints within **existing** settings router
  (`apps/api/app/admin_settings.py`):
  `GET /v1/settings/field-options?field_key=...`;
  `POST /v1/settings/field-options`;
  `PATCH /v1/settings/field-options/{id}`.
- Add a single paginated read for finance forms; never allow a member from one
  organization to infer another organization's options.
- Store `purpose_option_id` for new payouts while keeping the historical
  `purpose` text snapshot for audit/export and backward compatibility.
  Reject unknown/inactive IDs when creating a payment.
- Do not make security/business invariants configurable:
  ₹250 multiples, financial correction reason codes, OTP and consent
  evidence, webhook/sender permissions, currency and IST policy.

## Files to change for Phase 2

1. `apps/api/app/models.py` — organization-scoped field option data.
2. `apps/api/alembic/versions/*` — non-destructive migration.
3. `apps/api/app/admin_settings.py` — existing Settings endpoints and audit.
4. `apps/api/app/payouts.py` — validate/select purpose and retain text snapshot.
5. `apps/web/components/admin-settings-form.tsx` — inline Field Options
   panel below Organisation Settings, with Team Access retained.
6. `apps/web/components/payouts/payouts-workspace.tsx` — purpose select on
   Add Payout, recurring and one-time forms; older records display snapshot.
7. `apps/api/tests/test_admin_auth_settings.py`,
   `apps/api/tests/test_payouts.py`, `apps/web/e2e/*` — org isolation,
   role restrictions, duplicate labels, inactive history, migrations and UI.

## Acceptance

Owner can create/edit/reorder/deactivate options in the **same Settings view**,
then immediately use one of them in both payout flows; user cannot submit
a non-approved new purpose, and legacy data/financial history is unchanged.
CI must pass PostgreSQL migrations, API tests, Next.js and desktop/mobile
browser tests before merge.
