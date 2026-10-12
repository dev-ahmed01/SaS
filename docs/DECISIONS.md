# Confirmed business decisions and deferred integration dependencies

- **Currency:** INR. Default contribution ₹250, configurable by Admin; each sponsorship has an agreed amount. Extra money counts toward the current month only.
- **Sponsor lifecycle:** Prospects may be registered without paying. Two complete consecutive IST calendar months with **no verified payment** make a previously-paying sponsor inactive; on verification of a later payment they reactivate. Inactive sponsors receive **no further automatic reminders**, including promoter follow-ups for that sponsor. A partial payment breaks a zero-payment streak but may leave an outstanding balance.
- **Time:** `Asia/Kolkata` is authoritative for accounting and scheduled reminder days; UTC timestamps are retained in the database.
- **Reminders:** On the 5th, remind only active sponsors who have not satisfied their current-month agreed amount; on the 20th send each linked promoter one consolidated message of active/unpaid assigned sponsors. Actual sending requires bank statement freshness checks and opt-in.
- **Money received:** Existing UPI QR, **no payment gateway** in first release. Admin imports bank CSV/Excel, backend deduplicates credits and matches by reliable payer UPI IDs (multiple per sponsor if verified). Never match by ₹250 amount alone. Unmatched credits require Admin review. Confirmations are sent only after reliable matching.
- **Admin:** One `Admin` role controls business settings and financial workflows for the first version. No separate Configuration Manager role. Production permissions are enforced server-side.
- **Settings:** Business values are versioned and editable, while validations, reconciliation and access controls are tested code. No default user/password.
- **Payouts:** Active means recurring monthly payout plans; one-time payouts remain distinct records, not failed payouts.
- **Automation:** Pabbly orchestrates WhatsApp workflows via authenticated backend APIs; FastAPI/PostgreSQL are the financial source of truth.

## External dependencies (explicit non-blockers for Phases 01–07)

1. **Bank/statement:** The bank and export layout are unknown; obtain an anonymized sample containing UPI credit narration to implement the Phase-08 adapter.
2. **WhatsApp:** Meta Business sender, approved templates, billing and opt-in have not been configured; required for Phase 11.
3. **Payout categories:** Foundation to confirm expense/beneficiary categories before Phase 09.
4. **Sponsor start month:** Foundation to confirm initial due month at activation before Phase 06 acceptance.
5. **Late statement imports:** Define policy for suppressed reminders when available bank data is stale; default must fail closed (do not send).
