# Sponsor a Salah — Saasyto 10,000-recipient queue (controlled release)

This change raises **capacity of approved campaign queues to 10,000 recipients**.
It does **not** authorize sending to 10,000 people, establish Saasyto account
throughput, or prove WhatsApp delivery. The first live rollout must be separately
approved and monitored. All default staging transport settings remain **OFF**.

## Sources and provider uncertainty

Saasyto advertises API integration and webhooks, including outgoing events, on
its official site: https://saasyto.com/send-bulk-broadcast-whatsapp-messages-in-2024/

That public page does **not** specify a verified requests-per-minute limit or a
documented idempotency key for the personal-account API used by this project.
Other Saasyto product pages describe distinct services and campaign sizes; those
are not guarantees for this API instance. Obtain written confirmation from
Saasyto for the actual connected instance before increasing throughput. Ask:
- maximum sustained send API calls/minute, daily send/account limits, and
  any anti-ban delay or recipient quality restrictions;
- handling of HTTP 429 and whether the provider ever accepts a request despite
  a client timeout;
- signed webhook payload/signature format and correlation IDs for
  submitted, delivered, read and failed messages;
- whether the endpoint supports idempotency keys and status lookup.

Do not assume HTTP 2xx equals delivery or retry ambiguous errors.

## Updated limits

- Campaign recipient review: 12,000 candidate contacts (headroom for exclusions).
- Single Saasyto campaign approval: **10,000 eligible recipients**.
- Monthly reminder preparation: 12,000 sponsor/recipient safety caps.
- Per-send live checks are **targeted**, not a full-audience scan. Consent and
  shared-number opt-out are still checked at the moment of dispatch.
- Queue claims are durable and at-most-once. An unknown provider result stays
  **unknown**, never blindly re-queued.
- A new `saasyto_dispatch_throttles` PostgreSQL table reserves a sender slot
  before external I/O. Every worker using the same database and configured
  `SAASYTO_INSTANCE_ID` shares the same gate.

## Throughput

`SAASYTO_MAX_ATTEMPTS_PER_MINUTE` defaults to **12/min**, with a
validated technical range of 1–120/min. The higher bound is only a software
validation ceiling, **not** a provider-approved sending speed.

At 12 requests/minute, 10,000 requests require **at least ~13 hours 54 minutes**
assuming each recipient remains eligible, no outages, and no throttling beyond
the configured limit. At 30/minute it is **at least ~5 hours 34 minutes**,
but 30/minute must not be selected without approval from Saasyto.
Those are lower bounds for submission *attempts*, not delivery.

Use the **single supervised VPS worker** after explicit rollout approval:

```bash
# Run from the repository root in the approved runtime with its private secrets.
# Do NOT start this before the provider and sender are approved.
python scripts/saasyto_tick.py --loop --interval-seconds 2
```

The polling interval only checks for available work. The PostgreSQL reservation,
not that interval, enforces the sender's rate. Run under systemd or an equivalent
process supervisor for restart-on-failure. Do not put the runner token in a
shell command, unit ExecStart, GitHub Actions logs, or the repository.

Required environment for the worker:
- `SAS_API_PUBLIC_ORIGIN` — approved HTTPS CRM origin;
- `SAASYTO_RUNNER_SECRET` — same 32+ character secret as API.

Required API environment:
- `SAASYTO_DELIVERY_ENABLED=false` until approved;
- `SAASYTO_SENDER_APPROVED=false` until verified;
- `SAASYTO_MAX_ATTEMPTS_PER_MINUTE=12` conservative default;
- `SAASYTO_INSTANCE_ID`, `SAASYTO_ACCESS_TOKEN`, `SAASYTO_RUNNER_SECRET`
  configured privately;
- `SAASYTO_ENABLE_AFTER` timezone-aware activation cutoff.

**The existing `ops/staging/compose.yaml` hard-disables outbound messaging**;
do not edit that gate merely to test scale. Rollout to production requires a
separate approved deployment and secret configuration.

## Operational checks

1. Apply Alembic migration `0024_saasyto_sender_throttle` before deploying
   the new API.
2. Take and verify a PostgreSQL backup; keep rollback instructions.
3. Smoke-test 1 approved test number, then 10 and 100 genuinely opted-in contacts.
4. Check `queued`, `claimed`, `accepted_unverified`, `unknown`,
   `rejected` and `suppressed` in campaign results. Validate no double
   submission when the worker is restarted or two workers poll concurrently.
5. Stop dispatch using the existing delivery kill switch or campaign
   cancellation if error rates increase.
6. Only increase the sender rate after provider approval, observed capacity and
   a supervised soak test. Do not auto-resend uncertain outcomes.
7. Run a synthetic, **no-provider-I/O** 10k recipient preparation/load test
   against a disposable database before authorizing a 10k live campaign.

## Important existing functionality boundaries

- The Saasyto campaign queue is explicitly approved by an admin.
- The `reminders.py` module **prepares** reminder batches but is not itself
  an outbound WhatsApp sender; monthly automation rules in
  `communication_rules` are currently configuration, not a running auto-sender.
  Scaling the preparation limit does not wire automatic monthly delivery.
- Provider acceptance is reported only as `accepted_unverified`. Actual
  delivered/read statuses require a verified, authenticated Saasyto webhook or
  official provider status endpoint, which is not yet integrated.
- A queue claim committed immediately before an external request may remain
  `claimed` if a process crashes. Investigate that state rather than
  automatically replaying it.
- The rate gate is per Saasyto instance within **one database**. Separate CRM
  databases or other applications using the same instance do not share this
  limit unless additional external coordination is implemented.

## Test gates

```bash
cd apps/api
python -m pytest -q tests/test_saasyto_campaign_dispatch.py \
  tests/test_saasyto_production_worker.py \
  tests/test_communication.py tests/test_reminders.py
```

No real WhatsApp messages should be sent by tests.
