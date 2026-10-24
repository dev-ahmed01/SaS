"""Run the private Saasyto due-message tick from an approved scheduler.

Use as the command of a private Render Cron Job or equivalent after deployment:
    python scripts/saasyto_tick.py
Only aggregate results are printed. Secrets are sent solely to the configured
HTTPS API endpoint, never displayed. Scheduler must not run until signed off.
"""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NeverRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Never forward a private runner secret to a redirected host.
        return None


def main() -> int:
    origin = os.environ.get("SAS_API_PUBLIC_ORIGIN", "").rstrip("/")
    secret = os.environ.get("SAASYTO_RUNNER_SECRET", "")
    parsed = urlsplit(origin)
    if not (
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and len(secret) >= 32
    ):
        print("Saasyto tick not configured")
        return 2
    url = origin + "/internal/saasyto/dispatch"
    request = Request(
        url,
        method="POST",
        headers={
            "X-Saasyto-Runner-Token": secret,
            "Accept": "application/json",
        },
        data=b"",
    )
    try:
        with build_opener(NeverRedirect()).open(request, timeout=90) as response:
            result = json.loads(response.read(4096))
            allowed = {"claimed", "accepted_unverified", "rejected",
                       "unknown", "suppressed"}
            safe = {key: int(value) for key, value in result.items()
                    if key in allowed and isinstance(value, int)}
            print(json.dumps({"saasyto_tick": safe}, sort_keys=True))
            return 0
    except (HTTPError, URLError, ValueError, OSError):
        print("Saasyto tick unavailable or rejected; no implicit retry")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
