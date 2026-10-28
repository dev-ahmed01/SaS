"""Production-only Saasyto worker for a private InterServer VPS container.

Never serves HTTP, never accepts recipient input and never runs in staging.
The campaign queue is approved by Admin separately and the database enforces
rolling-minute claim rate and one-attempt-per-recipient semantics.
"""
import argparse
import json
import time

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.saasyto_campaigns import _dispatch_due, _reconcile_stale_claims


def dispatch_once() -> int:
    cfg = get_settings()
    if not (
        cfg.app_env == "production"
        and cfg.saasyto_delivery_enabled
        and cfg.saasyto_sender_approved
        and cfg.saasyto_worker_enabled
    ):
        print("Saasyto worker inactive; production sender approval required")
        return 2
    try:
        with Session(get_engine()) as db:
            # A crash can interrupt a committed claim after the provider
            # accepted the message. Reconcile it as UNKNOWN; never retry.
            reconciled = _reconcile_stale_claims(db)
            outcome = _dispatch_due(db, cfg)
            if reconciled:
                outcome["unknown"] = outcome.get("unknown", 0) + reconciled
        # Only a sanitized count summary. Never print recipient addresses,
        # personalization, provider payloads, account tokens or OTP content.
        allowed = {"claimed", "accepted_unverified", "rejected", "unknown", "suppressed"}
        safe = {key: int(value) for key, value in outcome.items()
                if key in allowed and isinstance(value, int)}
        print(json.dumps({"saasyto_campaign_tick": safe}, sort_keys=True))
        return 0
    except Exception:
        # Durable claims remain in PostgreSQL and are NEVER automatically
        # retried if the process stops after a provider call.
        print("Saasyto worker unavailable; inspect protected application logs")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private production Saasyto worker")
    parser.add_argument("--once", action="store_true", help="One guarded dispatch tick")
    parser.add_argument("--interval-seconds", type=int, default=60,
                        help="Recurring poll interval, 15..3600 seconds")
    args = parser.parse_args(argv)
    if not 15 <= args.interval_seconds <= 3600:
        parser.error("Worker interval must be between 15 and 3600 seconds")
    if args.once:
        return dispatch_once()
    cfg = get_settings()
    if not (
        cfg.app_env == "production"
        and cfg.saasyto_delivery_enabled
        and cfg.saasyto_sender_approved
        and cfg.saasyto_worker_enabled
    ):
        print("Saasyto worker disabled; no message submitted")
        return 2
    print("Private production Saasyto campaign worker active")
    try:
        while True:
            if dispatch_once() != 0:
                return 1
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        print("Private Saasyto worker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
