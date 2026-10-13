# Phase 04 — Prospects Management

## Functional scope

The locked Sponsor a Salah web layout remains the source of truth. The Prospects area has exactly three tabs: **Add Prospect**, **Inactive**, and **All Prospects**. Admin login is required for every API and screen.

A candidate can register before paying, so the initial lifecycle status is **New**. **Current approved rule (supersedes the Phase 04 placeholder):** a sponsor becomes Inactive after two consecutive completed IST months with zero net Admin-attested recorded contributions and reactivates on any valid ₹250-tier recorded contribution. Neither lifecycle status nor the two-month threshold is Admin-editable. Bank-statement imports are deferred; Admin manually records actual received funds. Earlier Phase 04 tests may use synthetic fixture statuses.

## Stored fields

- Full name, E.164 phone and optional WhatsApp contact, area/city
- Agreed monthly contribution in integer paise, minimum ₹250 and in ₹250 increments (the Admin's current valid default fills an omitted amount). New incoming manual contributions follow the same denominations.
- Follow-up/contact dates, notes, and an explicit, default-off WhatsApp consent flag
- Status and first-payment history columns reserved for the future accounting engine
- Optional multiple UPI identifiers (up to five), stored as **HMAC-SHA256 digests** with **masked display only**; IDs are **unverified** until bank/statement reconciliation

Registration uses an optional UUID request ID so client retries return the same record rather than duplicating a donor; conflicting reuse is rejected.\n\nThe full payer UPI ID is never persisted in this module. Reconciliation in Phase 08 can apply the same digest to the normalized incoming bank VPA and compare equality. **A shared payer ID does not establish which sponsor paid**: where a payer funds two sponsors, the match will remain ambiguous and require Admin review.

**UPI_MATCH_SECRET** must remain stable across deployments. Set a unique 32+ character secret for staging/production, separately from AUTH_SECRET. A key change requires a controlled re-registration or multi-key rotation strategy. Never commit real secrets or bank statements.

## API contract

- `GET /v1/prospects?status=&q=&limit=&offset=&include_archived=`
- `POST /v1/prospects` creates a candidate, status New
- `GET /v1/prospects/{uuid}`
- `PATCH /v1/prospects/{uuid}` requires current `version` and rejects stale edits
- `DELETE /v1/prospects/{uuid}` soft-archives; requires `If-Match` version
- `POST /v1/prospects/{uuid}/restore` restores an archived record
- `POST /v1/prospects/{uuid}/upi-ids` adds an unverified masked ID
- `DELETE /v1/prospects/{uuid}/upi-ids/{uuid}` revokes an identifier, never silently removes its audit history

Mutations require Admin session and CSRF. Every read/write scopes to the Admin's organization, with validated fields, bounded pagination and auditable mutations. Audit events record field names and record versions, rather than duplicating personal details. This phase does not send messages, execute payments, or infer successful donations.

## Verification

```bash
cd apps/api
python -m ruff check .
python -m pytest -q
python -m alembic upgrade head
python -m alembic check
```

```bash
cd apps/web
npm ci
npm test
npm run typecheck
npm run build
```

GitHub CI also runs the authenticated desktop/mobile Chromium suite. Use synthetic data only. Full accessibility acceptance, bank adapter and WhatsApp onboarding remain later production gates.

## Open decisions

- The foundation's bank name, transaction export format and available payer identifiers (Phase 08)
- Meta WhatsApp setup, approved template and opt-in onboarding (Phase 11)
- Sponsor start month and first monthly due (Phase 06)
