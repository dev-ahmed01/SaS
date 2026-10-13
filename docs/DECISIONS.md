# Confirmed Sponsor a Salah business decisions

- Admin-only Foundation web app using the approved left sidebar and Bricolage Grotesque/Poppins green-white UI.
- Currency INR, initial monthly contribution ₹500, configurable per sponsor and by Admin without changing historical dues.
- Registration before first payment is allowed. Monthly accounting uses Asia/Kolkata.
- A sponsor becomes Inactive after two consecutive missed complete months and does not receive scheduled reminders while Inactive. A payment can reactivate a sponsor. **Clarification required:** Phase 06 currently counts a full month's verified payment as the reactivation threshold; confirm whether partial payment should also count.
- One current promoter per sponsor. Sponsor reminders are planned for the 5th (only eligible unpaid sponsors), consolidated promoter reminders for the 20th (one message per promoter).
- **Latest Foundation direction:** Admin **manually enters** payments after checking actual receipt. Bank CSV/Excel statement importer and bank-specific reconciliation are deferred. Entries must include sponsor, amount, month, receipt date, payment method and a unique reference.
- After entry, the system prepares a consent-checked **WhatsApp confirmation event** automatically. Actual delivery via Pabbly/WhatsApp Business is **not enabled** until sender, approved template, consent, secure authentication, deduplication, delivery callbacks, and retries are configured. Never claim sent/delivered without provider confirmation.
- One Admin role manages financial records/settings. Payout Active means recurring; one-time payout remains separate.
- Financial records remain in PostgreSQL, under audited FastAPI transaction controls, with a Next.js same-origin gateway. No hardcoded donation amounts.

## Pending business and production inputs

1. Proof standards for manually entered UPI/bank payments and numbered cash receipts.
2. Approved corrections/reversals and potential second-person review for large amounts.
3. Partial payment status/reactivation policy.
4. WhatsApp Business/Pabbly setup, template approval and opt-in language.
5. Payout categories, retention, backup drill, staging/UAT and production approval.
