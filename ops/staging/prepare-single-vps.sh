#!/usr/bin/env bash
# Initialize a fresh, empty single-VPS STAGING deployment.
# Never overwrite env files, keys, database volumes or existing donor data.
set -euo pipefail
umask 077

if [[ $# -ne 2 ]]; then
  echo "Usage: bash ops/staging/prepare-single-vps.sh <staging.domain.tld> <operations-email>" >&2
  exit 2
fi
HOSTNAME="$1"
EMAIL="$2"
if [[ ! "$HOSTNAME" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ || "$HOSTNAME" != *.* || "$HOSTNAME" == *..* ]]; then
  echo "STOP: supply a real lowercase staging DNS hostname, not an IP or sample name" >&2
  exit 2
fi
if [[ ! "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo "STOP: supply a valid operations email" >&2
  exit 2
fi
for tool in openssl python3; do
  command -v "$tool" >/dev/null || { echo "STOP: missing $tool" >&2; exit 2; }
done
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIR="$ROOT/ops/staging"
for file in "$DIR/.env" "$DIR/.env.api" "$DIR/.env.db" "$DIR/postgres-tls/server.crt" "$DIR/postgres-tls/server.key"; do
  if [[ -e "$file" ]]; then
    echo "STOP: $file exists. Never overwrite staging credentials or certificates." >&2
    exit 2
  fi
done
mkdir -m 700 -p "$DIR/postgres-tls"
DB_PASSWORD="$(openssl rand -hex 24)"
AUTH_SECRET="$(openssl rand -hex 48)"
UPI_SECRET="$(openssl rand -hex 48)"
OTP_SECRET="$(openssl rand -hex 48)"
cat > "$DIR/.env" <<EOF
STAGING_HOST=$HOSTNAME
ACME_EMAIL=$EMAIL
EOF
cat > "$DIR/.env.db" <<EOF
POSTGRES_DB=sas_staging
POSTGRES_USER=sas_staging
POSTGRES_PASSWORD=$DB_PASSWORD
EOF
cat > "$DIR/.env.api" <<EOF
APP_ENV=staging
LOCAL_DEMO_LOGIN_ENABLED=false
DATABASE_URL=postgresql+psycopg://sas_staging:$DB_PASSWORD@db:5432/sas_staging?sslmode=require
AUTH_SECRET=$AUTH_SECRET
UPI_MATCH_SECRET=$UPI_SECRET
OTP_SECRET=$OTP_SECRET
MESSAGING_DELIVERY_ENABLED=false
MESSAGING_SENDER_APPROVED=false
OTP_DELIVERY_ENABLED=false
OTP_SAASYTO_ENABLED=false
OTP_ACTIVATION_NOTICE_ENABLED=false
SAASYTO_DELIVERY_ENABLED=false
SAASYTO_SENDER_APPROVED=false
EOF
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 \
  -keyout "$DIR/postgres-tls/server.key" \
  -out "$DIR/postgres-tls/server.crt" \
  -subj "/CN=db" \
  -addext "subjectAltName=DNS:db" >/dev/null 2>&1
chmod 600 "$DIR/.env" "$DIR/.env.api" "$DIR/.env.db" "$DIR/postgres-tls/server.key"
chmod 644 "$DIR/postgres-tls/server.crt"
echo "Prepared PRIVATE staging secrets and internal PostgreSQL TLS certificate."
echo "No donor data has been migrated and outbound WhatsApp remains OFF."
echo "Next: verify DNS, then follow ops/staging/SINGLE_VPS.md."
