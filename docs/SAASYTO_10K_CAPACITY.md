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

Saasyto's public **personal-account campaign guide** recommends a **90-120
second gap** between messages to reduce sender blocking risk:
https://saasyto.com/product/saasyto-personal-whatsapp-subscription/
This is **not a documented rate limit for our exact direct-send API**. Until
Saasyto confirms which service our instance uses, production defaults to
conservative sender-wide spacing; a 10k daily turnaround is **not promised**.

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
  organization), `SAASYTO_CAMPAIGN_MIN_INTERVAL_SECONDS=90` between
  individual claim attempts across campaigns, and
  `SAASYTO_RATE_LIMIT_PAUSE_MINUTES=15`. The interval is intentionally
  restrictive for linked personal senders; lowering it requires the
  provider's written rate authorization and a controlled rehearsal.
- A database row lock on the organization plus a rolling claim count
  prevents **concurrent campaign workers in the same organization**
  from claiming beyond its configured quota. Do not start extra
  sender instances as a workaround for provider quotas.
- A provider **HTTP 429** records a terminal *rejected* attempt and
  pauses all approved campaigns for that Foundation sender for 15 minutes;
  the rejected member is **not** implicitly retried. If that was the
  last queued recipient, its run is completed rather than left hanging.
- Aggregated counts are calculated in SQL across the full queue;
  recipient lists are paged (100 rows/page). Counts do not pretend
  Saasyto HTTP acceptance equals WhatsApp *delivered* or *read*.
- No automatic retries of claimed, unknown, rejected or timed-out
  contacts. Manual resolution needs explicit provider evidence.
- A claim left in progress by a worker crash for **more than 15 minutes**
  becomes `unknown` during the next authenticated dispatch tick. It is never
  submitted again automatically; a completed queue is marked completed.
- A composite claim-time index keeps the rolling minute/gap checks efficient
  as queued recipient history grows.

**Not included:** verified provider throughput; a documented signed
delivery/read webhook; production-recipient load testing; automatic
monthly-rule-to-campaign send; priority scheduling between OTP and
campaign sends; provider-account-wide rate limiting shared with
one-off OTP/receipts. The quota applies to the campaign worker only.

## Throughput planning (not a performance guarantee)

The **default** 90-second minimum gap means the personal-sender
starting configuration will not approach the 10/minute quota. For 10,000
attempts it needs at least **250 hours (~10.4 days)** even with a frequent
scheduler; a 60-second polling cadence may stretch this to nearly 14 days.

For a provider-confirmed official/API sender, the Foundation can explicitly
reduce `SAASYTO_CAMPAIGN_MIN_INTERVAL_SECONDS` and adjust the batch/minute
caps. At an **approved** 10/min sustained rate, 10k requires at least
16 h 40 min; at 30/min, at least 5 h 34 min. These are throughput calculations,
not delivery SLAs. 10k/day requires more than 6.94 requests/minute sustained
and written provider authorization. A 15-second worker tick and a bounded batch
may approach 30/min only when the interval and minute budget permit it.
Batch size is capped at 15 requests/tick to stay below the 90-second scheduler
timeout under the connector's 5-second/request timeout. Network response time,
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
