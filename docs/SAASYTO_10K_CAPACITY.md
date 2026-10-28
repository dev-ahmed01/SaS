# Saasyto 10,000-recipient capacity — verified limits and launch controls

Status: **engineering capacity preparation, not approved 10k live sending**.

## What we actually verified

Saasyto advertises high-volume WhatsApp campaigns and API connectivity:

- https://saasyto.com/whatsapp-personal/
- https://saasyto.com/send-bulk-broadcast-whatsapp-messages-in-2024/
- https://web.saasyto.com/pricing

The public pages **do not publish a reliable, numeric requests/minute
contract for the exact direct-send endpoint used by this CRM**. Marketing
claims of unlimited sends are not a guaranteed throughput or delivery SLA.
Saasyto's product categories (Official, Personal, Virtual) are not
interchangeable and must not be used to infer one another's quotas.

Ask Saasyto for written confirmation of the sending rate, burst limits,
429 behavior and Retry-After handling, sender/account quotas, webhook
signatures, delivery/read receipts, opt-in requirements and service policy
for Foundation reminders. Do not assume any volume bypasses recipient
consent or anti-spam policies.

## What this change implements

- Up to **10,000 contacts per communication preparation and approved
  campaign** (previously 2,000 and 500 respectively).
- Up to **10,000 eligible sponsors per reminder preparation**. The
  reminder module still only **prepares** the monthly batch; it is *not*
  an automatically connected Saasyto send schedule.
- Durable, tenant-bound, one-time recipient queue; explicit Admin
  preparation and approval; live opt-out and status rechecks at claim time.
- Configurable campaign worker throughput with conservative defaults:
  `SAASYTO_CAMPAIGN_BATCH_SIZE=10` per private worker tick,
  `SAASYTO_CAMPAIGN_MAX_PER_MINUTE=10` (rolling 60 seconds, per
  organization), `SAASYTO_RATE_LIMIT_PAUSE_MINUTES=15`.
- A database row lock on the organization plus a rolling claim count
  prevents **concurrent campaign workers in the same organization**
  from claiming beyond its configured quota. Do not start extra
  sender instances as a workaround for provider quotas.
- A provider **HTTP 429** records a terminal *rejected* attempt and
  pauses the *remaining unsubmitted* campaign queue for 15 minutes;
  the rejected member is **not** implicitly retried.
- Aggregated counts are calculated in SQL across the full queue;
  recipient lists are paged (100 rows/page). Counts do not pretend
  Saasyto HTTP acceptance equals WhatsApp *delivered* or *read*.
- No automatic retries of claimed, unknown, rejected or timed-out
  contacts. Manual resolution needs explicit provider evidence.

### Private VPS dispatcher scaffolding

The API image contains an optional, production-only CLI:

```bash
python -m app.saasyto_vps_worker --once
python -m app.saasyto_vps_worker --interval-seconds 60
```

It runs `_dispatch_due` directly against the private PostgreSQL queue
rather than exposing `/internal/saasyto/dispatch` to the public Caddy
reverse proxy. It **refuses to run** unless all four gates are true:
`APP_ENV=production`, `SAASYTO_DELIVERY_ENABLED=true`,
`SAASYTO_SENDER_APPROVED=true`, and `SAASYTO_WORKER_ENABLED=true`.
These values are **not** set in the VPS staging deployment; no worker
service is automatically provisioned or started. Configure a supervised
production worker, account-level alerting and rollback only after the
provider pilot passes.

**Not included:** verified provider throughput; a documented signed
delivery/read webhook; production-recipient load testing; automatic
monthly-rule-to-campaign send; priority scheduling between OTP and
campaign sends; provider-account-wide rate limiting shared with
one-off OTP/receipts. The quota applies to the campaign worker only.

## Throughput planning (not a performance guarantee)

At the **default** campaign budget of 10 submissions/minute:

- 1,000 recipients: at least 100 minutes;
- 10,000 recipients: at least 1,000 minutes (~16 h 40 min).

At **30 submissions/minute** (only if confirmed and approved by
Saasyto) 10,000 requires at least ~5 h 34 min. A 60-second
worker tick with the default batch size only attempts 10/min regardless
of the configured minute cap; after approval, a 15-second poll interval
and a bounded batch size can safely approach 30/min. Batch size is
capped at 15 requests/tick to stay below the 90-second scheduler timeout
under the connector's 5-second/request timeout. Network response time,
consent suppression, provider downtime and pauses can add delay.

Do not change dispatch env settings to achieve a marketing target
without a written provider-approved rate and a synthetic rehearsal.

## Launch gates for InterServer

1. Keep `SAASYTO_DELIVERY_ENABLED=false` and
   `SAASYTO_SENDER_APPROVED=false` on the **staging** VPS. Our
   standard Compose stack forcibly disables sends. It does **not**
   launch an outbound sending worker.
2. Apply any pending PostgreSQL migrations and validate an encrypted
   backup and independent restore.
3. Rehearse 10k synthetic queue records, per-page results, 429
   handling, cancellation, crash/unknown behavior, two competing
   workers and tenant isolation with no provider network calls.
4. Confirm numeric provider rate, identity, contractual limitations
   and authenticated callback schema. Do not assume a webhook
   signature format from a different provider.
5. Require consent/opt-out evidence and Admin approval for each
   campaign, and reconcile sample provider responses with actual
   recipient observations before staged expansion (10 → 100 →
   1,000 → 10,000).
6. Use one controlled production worker with monitoring, private
   secrets, daily send budget, a manual stop switch and protected
   status dashboards. Provisioning the VPS by itself does not
   activate automatic delivery.
7. Audit real campaign outcomes with *accepted_unverified*,
   *rejected*, *unknown*, *queued* and *claimed* separately.
   Block repeated blind sends when the outcome is uncertain.
