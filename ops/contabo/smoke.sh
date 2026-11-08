#!/usr/bin/env bash
# Run from an operator terminal after DNS and HTTPS are working.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: bash ops/contabo/smoke.sh sas.your-real-domain.tld" >&2
  exit 2
fi
HOST="$1"
if [[ ! "$HOST" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ || "$HOST" != *.* ]]; then
  echo "STOP: supply a real DNS hostname" >&2; exit 2
fi
URL="https://$HOST"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$URL/health/live" \
  | grep -q '"status":"ok"'
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$URL/health/ready" \
  | grep -q '"status":"ready"'
curl --fail --silent --show-error --proto '=https' --tlsv1.2 "$URL/login" \
  >/dev/null
code="$(curl --silent --show-error --proto '=https' --tlsv1.2 \
   --output /dev/null --write-out '%{http_code}' "$URL/v1/auth/session")"
if [[ "$code" != 401 ]]; then
  echo "STOP: unauthenticated API did not deny session access (HTTP $code)" >&2
  exit 1
fi
echo "HTTPS certificate, API readiness, login screen, and unauthenticated access denial passed."
echo "Still perform signed-in business UAT and backup restore before importing real donor data."
