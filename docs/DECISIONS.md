# Confirmed Sponsor a Salah business decisions

- Admin-only Foundation web app using the approved left sidebar and Bricolage Grotesque/Poppins green-white UI.
- Currency INR. Approved 13 October 2026: new sponsorship commitments are positive multiples of ₹250, with a ₹250 default. Existing agreements and historical statements do not change. **Updated direction: every new recorded incoming contribution must also be at least ₹250 and a multiple of ₹250.** No sub-₹250 or off-tier manual receipts are accepted; existing immutable historical receipts are left intact.
- Registration before first payment is allowed. Monthly accounting uses Asia/Kolkata.
- Approved 13 October 2026: two consecutive completed IST calendar months with zero net recorded contribution activity cause inactivity. Any **valid** positive net recorded contribution, including a receipt allocated to an older billing month, reactivates. Activity uses the recorded/verified IST date while balances use billing allocation. Reversed receipts do not count. Months without an obligation during archival do not form a missed-month streak. Inactive sponsors receive no scheduled reminders.
- One current promoter per sponsor. Sponsor reminders are planned for the 5th (only eligible unpaid sponsors), consolidated promoter reminders for the 20th (one message per promoter).
- **Latest Foundation direction:** Admin **manually enters** payments after checking actual receipt. Bank CSV/Excel statement importer and bank-specific reconciliation are deferred. Entries must include sponsor, amount, month, receipt date, payment method and a unique reference.
- After entry, the system prepares a consent-checked **WhatsApp confirmation event** automatically. Actual delivery via Pabbly/WhatsApp Business is **not enabled** until sender, approved template, consent, secure authentication, deduplication, delivery callbacks, and retries are configured. Never claim sent/delivered without provider confirmation.
- One Admin role manages financial records/settings. Payout Active means recurring; one-time payout remains separate.
- Financial records remain in PostgreSQL, under audited FastAPI transaction controls, with a Next.js same-origin gateway. No hardcoded donation amounts. 
- Mistaken manual entries can be **fully reversed**, never silently deleted: preserve original evidence, correct net accounting, suppress unsent confirmation, and record Admin + reason in immutable audit history. Reversal is not a refund.

## Pending business and production inputs

1. Proof standards for manually entered UPI/bank payments and numbered cash receipts.
2. Foundation authorization policy for reversals and potential second-person review for large amounts; the technical single-Admin reversal flow is implemented, but financial governance requires approval.
3. **Updated direction:** no partial-contribution feature. Each new receipt starts at ₹250 and follows ₹250 increments. A valid receipt reactivates, and the ledger continues to show any remaining unpaid obligation without rounding or fabricating collections.
4. WhatsApp Business/Pabbly setup, template approval and opt-in language.
5. Payout categories, retention, backup drill, staging/UAT and production approval.

## Phase 09 — Payouts implementation boundaries

- **Payouts Add, Active, All** are real PostgreSQL-backed Admin modules. Recurring monthly commitments and one-time expenses are distinct. All retains both types and attested payments.
- Creating a payout plan does not transfer money. Recording `paid` requires explicit Admin attestation and unique outgoing reference. No gateway/disbursement integration is authorized.
- Recurring pause/resume/close becomes effective next IST calendar month; past obligations and payments are not rewritten. Status history remains auditable.
- **Pending approval:** proof and authority for outgoing payouts, second-person approval threshold, adjustments and historical corrections, amount change policy and partial/advance disbursement rules.

## Phase 10 — Reminder eligibility and safe preparation

- The Admin **Reminders → WhatsApp** screen shows live sponsor/promoter previews in Kolkata time; it cannot send messages.
- Default sponsor reminder day is the 5th, promoter follow-up the 20th; both are read from Admin Settings.
- A sponsor is ineligible when archived, two completed missed months make them inactive, the current month is fully paid, or direct WhatsApp consent is missing. Never use a stale Prospects lifecycle cache to decide eligibility.
- A single promoter message represents all eligible currently assigned unpaid sponsors; promoter activity and consent are required. No duplicate promoter notifications for each sponsor.
- Preparation runs only on the configured IST day, is Admin-initiated/idempotent and records no provider deliveries. Phase 11 will add scheduling and secure Pabbly/WhatsApp delivery with live rechecking at dispatch.
- Valid ₹250-tier receipts reactivate; direct reminders to registered New sponsors and promoter balance disclosures still require separate approval.
