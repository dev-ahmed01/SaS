#!/usr/bin/env bash
# Non-destructive validation of the prepared production stack before migration.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/../.."
for file in "$DIR/.env" "$DIR/.env.db" "$DIR/.env.api" \
            "$DIR/postgres-tls/ca.crt" "$DIR/postgres-tls/server.crt" \
            "$DIR/postgres-tls/server.key"; do
  [[ -f "$file" ]] || { echo "STOP: private configuration missing: $file" >&2; exit 2; }
done
for executable in docker openssl python3; do
  command -v "$executable" >/dev/null || { echo "STOP: missing $executable" >&2; exit 2; }
done
openssl verify -CAfile "$DIR/postgres-tls/ca.crt" "$DIR/postgres-tls/server.crt" >/dev/null
openssl x509 -in "$DIR/postgres-tls/server.crt" -checkhost db -noout \
  | grep -q 'does match'
docker network inspect emlen_ingress >/dev/null
docker compose --env-file "$DIR/.env" \
  -f "$DIR/compose.production.yaml" config --quiet
python3 - "$DIR" <<'PY'
import json
import subprocess
import sys

root = sys.argv[1]
cmd = ["docker", "compose", "--env-file", f"{root}/.env",
       "-f", f"{root}/compose.production.yaml", "config", "--format", "json"]
services = json.loads(subprocess.check_output(cmd, text=True))["services"]
assert set(services) == {"db", "api", "web"}, "Worker must be opt-in only"
assert all(not service.get("ports") for service in services.values()), "Host port published"
assert set(services["db"]["networks"]) == {"private"}, "PostgreSQL exposed"
assert set(services["web"]["networks"]) == {"ingress"}, "Next.js not isolated"
assert set(services["api"]["networks"]) == {"private", "ingress"}
env = services["api"]["environment"]
assert env["APP_ENV"] == "production"
assert env["LOCAL_DEMO_LOGIN_ENABLED"] == "false"
for flag in (
    "SAASYTO_DELIVERY_ENABLED", "SAASYTO_SENDER_APPROVED",
    "SAASYTO_WORKER_ENABLED", "SAASYTO_AUTO_REMINDERS_ENABLED",
    "OTP_SAASYTO_ENABLED", "OTP_DELIVERY_ENABLED",
):
    assert env.get(flag, "false") == "false", f"STOP: {flag} should be off at first cutover"
assert "sslmode=verify-full" in env["DATABASE_URL"]
print("SaS production preflight passed: private DB, verified TLS, no host ports, sender OFF.")
PY
