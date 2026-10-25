"""Local Saasyto dispatch worker: only the opt-in, one-recipient loopback pilot.

Run from apps/api with the existing ignored .env:
  python -m app.saasyto_local_worker --port 8001 --once
  python -m app.saasyto_local_worker --port 8001

The script never calls Saasyto itself. It invokes the authenticated localhost
dispatch route, which rechecks the recipient's live consent and address before
sending. No inbound internet server, public tunnel, or Render scheduler needed.
"""
import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from app.config import get_settings


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def dispatch_once(*, port: int) -> bool:
    """Perform one private API tick with no proxies, redirects, or sensitive logs."""
    settings = get_settings()
    if not (
        settings.app_env == "development"
        and settings.local_demo_login_enabled
        and settings.saasyto_local_test_enabled
        and settings.saasyto_delivery_enabled
        and settings.saasyto_sender_approved
    ):
        print("Local Saasyto pilot is disabled; no messages submitted")
        return False
    secret = (
        settings.saasyto_runner_secret.get_secret_value()
        if settings.saasyto_runner_secret else ""
    )
    if not 1 <= port <= 65535 or len(secret) < 32:
        print("Local worker configuration invalid")
        return False
    request = Request(
        f"http://127.0.0.1:{port}/internal/saasyto/dispatch",
        data=b"",
        method="POST",
        headers={"X-Saasyto-Runner-Token": secret, "Accept": "application/json"},
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(
            request, timeout=30,
        ) as response:
            result = json.loads(response.read(4096))
            allowed = {
                "claimed", "accepted_unverified", "rejected", "unknown", "suppressed",
            }
            totals = {
                key: value for key, value in result.items()
                if key in allowed and type(value) is int
            }
            print("Local Saasyto dispatch:", json.dumps(totals, sort_keys=True))
            return True
    except (HTTPError, URLError, ValueError, TypeError, OSError):
        print("Local dispatch unavailable or rejected; inspect API server logs")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded Saasyto loopback worker")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--once", action="store_true", help="Perform one private queue tick")
    parser.add_argument(
        "--interval-seconds", type=int, default=30,
        help="Seconds between polls, minimum 15 (default 30)",
    )
    options = parser.parse_args()
    if not 1 <= options.port <= 65535 or options.interval_seconds < 15:
        parser.error("Port must be valid and interval must be at least 15 seconds")
    if options.once:
        return 0 if dispatch_once(port=options.port) else 1

    cfg = get_settings()
    if not (
        cfg.app_env == "development"
        and cfg.local_demo_login_enabled
        and cfg.saasyto_local_test_enabled
        and cfg.saasyto_delivery_enabled
        and cfg.saasyto_sender_approved
    ):
        print("Local Saasyto pilot disabled; worker not started")
        return 2

    print("Local Saasyto worker started; press Ctrl+C to stop")
    try:
        while True:
            dispatch_once(port=options.port)
            time.sleep(options.interval_seconds)
    except KeyboardInterrupt:
        print("Local Saasyto worker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
