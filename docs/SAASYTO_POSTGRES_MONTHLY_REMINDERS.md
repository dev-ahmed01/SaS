# PostgreSQL-only Saasyto monthly reminders (draft integration)

This branch ports the standing 5th/20th IST scheduler from the retired MySQL trial **without** importing MySQL schema or switching off existing financial ledger/receipt routes.

- Default OFF: `SAASYTO_AUTO_REMINDERS_ENABLED=false`. Enabling requires approved production Saasyto private worker, sender permission, and legacy Pabbly transport disabled.
- Organization automation must also be enabled. The worker runs only on the configured IST day, uses the existing PostgreSQL-recipient queue and rechecks consent, assignments, unpaid balance and request identity at dispatch.
- Existing monthly batches block duplicate preparation. A manual reminder batch cannot preempt the automatic batch while the flag is active.
- Claims remain one-shot; interrupted attempts become unknown, not automatic retries. Queued reminders expire after their scheduled IST day.
- A sender with a 90-second pacing gap cannot deliver 10,000 same-day reminders. Written provider approval of throughput is required before scheduling at scale.
- **No sending or production activation is performed by code changes alone.** Real Saasyto delivery, callbacks, receipt acknowledgements, backups and VPS smoke tests remain separate acceptance gates.

Only activate after a documented Foundation rollout and a test with synthetic data and a single consented real device.