#!/usr/bin/env bash
# Prepare a NEW production installation; never reset an existing database.
# No outbound messages are enabled and no donor records are copied.
set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
  echo "Usage: bash ops/contabo/prepare-production.sh <sas-approved-hostname>" >&2
  exit 2
fi
HOST="$1"
if [[ ! "$HOST" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ||
      "$HOST" != *.* || "$HOST" == *..* || "$HOST" == *.example.* ]]; then
  echo "STOP: supply your actual, approved lowercase DNS hostname (not a sample)" >&2
  exit 2
fi
for executable in openssl; do
  command -v "$executable" >/dev/null || {
    echo "STOP: missing $executable" >&2; exit 2;
  }
done
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for filename in .env .env.api .env.db postgres-tls/ca.crt postgres-tls/ca.key \
                postgres-tls/server.crt postgres-tls/server.key; do
  if [[ -e "$DIR/$filename" ]]; then
    echo "STOP: refusing to overwrite existing configuration or TLS keys." >&2
    exit 2
  fi
done
mkdir -m 700 -p "$DIR/postgres-tls"
DB_SECRET="$(openssl rand -hex 32)"
AUTH_SECRET="$(openssl rand -hex 48)"
UPI_SECRET="$(openssl rand -hex 48)"
OTP_SECRET="$(openssl rand -hex 48)"
RUNNER_SECRET="$(openssl rand -hex 48)"

cat > "$DIR/.env" <<EOF
SAS_HOST=$HOST
EOF
cat > "$DIR/.env.db" <<EOF
POSTGRES_DB=sas_production
POSTGRES_USER=sas_prod
POSTGRES_PASSWORD=$DB_SECRET
EOF
cat > "$DIR/.env.api" <<EOF
APP_ENV=production
DATABASE_URL=postgresql+psycopg://sas_prod:$DB_SECRET@db:5432/sas_production?sslmode=verify-full&sslrootcert=/run/postgres-ca/ca.crt
AUTH_SECRET=$AUTH_SECRET
UPI_MATCH_SECRET=$UPI_SECRET
OTP_SECRET=$OTP_SECRET
LOCAL_DEMO_LOGIN_ENABLED=false
SAASYTO_LOCAL_TEST_ENABLED=false
SAASYTO_LOCAL_DYNAMIC_ENABLED=false
OTP_LOCAL_PILOT_ENABLED=false
MESSAGING_DELIVERY_ENABLED=false
MESSAGING_SENDER_APPROVED=false
PROMOTER_DISCLOSURE_APPROVED=false
SAASYTO_DELIVERY_ENABLED=false
SAASYTO_SENDER_APPROVED=false
SAASYTO_WORKER_ENABLED=false
SAASYTO_AUTO_REMINDERS_ENABLED=false
SAASYTO_INSTANCE_ID=
SAASYTO_ACCESS_TOKEN=
SAASYTO_RUNNER_SECRET=$RUNNER_SECRET
SAASYTO_ENABLE_AFTER=
OTP_SAASYTO_ENABLED=false
OTP_DELIVERY_ENABLED=false
OTP_ACTIVATION_NOTICE_ENABLED=false
EOF

# A private CA and a leaf certificate for Docker host 'db' provide verified
# PostgreSQL TLS; the CA private key is NEVER mounted in any running container.
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
  -keyout "$DIR/postgres-tls/ca.key" -out "$DIR/postgres-tls/ca.crt" \
  -subj "/CN=sas-private-db-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" >/dev/null 2>&1
openssl req -new -newkey rsa:3072 -nodes -sha256 \
  -keyout "$DIR/postgres-tls/server.key" \
  -out "$DIR/postgres-tls/server.csr" \
  -subj "/CN=db" >/dev/null 2>&1
cat > "$DIR/postgres-tls/server.ext" <<EOF
subjectAltName=DNS:db
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
EOF
openssl x509 -req -in "$DIR/postgres-tls/server.csr" \
  -CA "$DIR/postgres-tls/ca.crt" -CAkey "$DIR/postgres-tls/ca.key" \
  -CAcreateserial -days 365 -sha256 \
  -extfile "$DIR/postgres-tls/server.ext" \
  -out "$DIR/postgres-tls/server.crt" >/dev/null 2>&1
rm -f "$DIR/postgres-tls/server.csr" "$DIR/postgres-tls/server.ext" "$DIR/postgres-tls/ca.srl"
chmod 600 "$DIR/.env" "$DIR/.env.api" "$DIR/.env.db" \
          "$DIR/postgres-tls/ca.key" "$DIR/postgres-tls/server.key"
chmod 644 "$DIR/postgres-tls/ca.crt" "$DIR/postgres-tls/server.crt"
echo "Generated private production configuration (no credentials displayed)."
echo "PostgreSQL uses verify-full TLS; Saasyto/OTP/payout outbound actions remain OFF."
echo "Review ops/contabo/DEPLOY.md before applying migrations or using real records."
