# Phase 05 — Promoters and sponsor assignments

## Locked UI

Three horizontal tabs inside the same left-sidebar website:
**Add Promoter**, **Active**, **All Promoters**.

Admin creates promoters with name, primary phone (E.164 normalization), optional WhatsApp contact, area, notes and recorded consent. The promoter is **Active by default**. Admin may deactivate/reactivate a promoter; this is **not** sponsor payment status.

The edit screen includes the sponsor assignment list, search and Assign / Unassign. No new global navigation module is added. Typography remains Bricolage Grotesque (headings, 600/700) + Poppins (body, 400/500/600), using the locked green-white scheme.

## Business and safety rules

- Each sponsor may have **one current primary promoter**. A promoter may manage many sponsors. Historical links persist after reassigning or removing a sponsor.
- Admin must unassign or transfer any sponsors **before deactivating** a promoter. This prevents silent omission from later follow-up lists.
- Sponsor assignments are organization-scoped and must not point to other organizations, including at the database level.
- Assignments reference prospects (including `New`) without changing sponsor payment status or pretending that payment has arrived.
- The future combined WhatsApp follow-up is scheduled through the organization-configured promoter day (currently 20) **only when eligibility, approved templates, explicit consent and Pabbly/WhatsApp onboarding are ready**. This phase does not send reminders.
- Admin-only protected APIs; mutation calls require CSRF, same-origin browser gateway and optimistic record versions.
- Promoter phone must be unique **within each organization**. Audit entries include entity IDs, changed field names and versions, not names, phone numbers or message bodies.
- Registration and editing do not import any real sponsor data. Test fixtures are synthetic.

## API routes

| Method | Route | Action |
|---|---|---|
| GET | `/v1/promoters?active=&q=&limit=&offset=` | Scoped list |
| POST | `/v1/promoters` | Register promoter |
| GET | `/v1/promoters/{uuid}` | Read details |
| PATCH | `/v1/promoters/{uuid}` | Edit/activate/deactivate with version |
| GET | `/v1/promoters/{uuid}/sponsors?limit=&offset=` | Assigned sponsor list |
| PUT | `/v1/promoters/{uuid}/sponsors/{prospect_uuid}` | Assign/transfer, `If-Match` sponsor version |
| DELETE | `/v1/promoters/{uuid}/sponsors/{prospect_uuid}` | End assignment, `If-Match` sponsor version |

The partial unique index over `promoter_assignments(organization_id, prospect_id)` for `ended_at IS NULL` prevents multiple simultaneous current promoters for one sponsor. The database also enforces same-organization foreign keys.

## Verification and remaining gates

CI runs Ruff, pytest, PostgreSQL migrations/autogenerate drift and tenant-integrity smoke tests, frontend tests/typecheck/build and desktop/mobile Chromium E2E journeys.

Production follow-up sending **remains disabled**. Phase 06 implements contribution/subscription periods and payment-state policy; Phase 08 implements bank statement reconciliation; Phase 11 enables Pabbly-led WhatsApp reminders after the provider and message approvals.

Outstanding client confirmation: whether sponsor ownership should always be single-primary promoter or can support shared co-promoters. Phase 05 implements **one primary promoter**; any change must be approved and migrated deliberately.
