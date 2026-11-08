#!/usr/bin/env bash
# Restore a chosen encrypted archive into a brand NEW Docker Compose project.
# Never points at the live sas-production volume and never starts web/API/worker.
set -euo pipefail
umask 077
if [[ $# -ne 2 ]]; then
  echo "Usage: SAS_RESTORE_ACK=ISOLATED_NEW_DATABASE AGE_IDENTITY_FILE=/private/key \\$0 /secure/backup.dump.age /secure/backup.dump.age.sha256" >&2
  exit 2
fi
if [[ "${SAS_RESTORE_ACK:-}" != "ISOLATED_NEW_DATABASE" ]]; then
  echo "STOP: explicit isolated-target acknowledgement required" >&2; exit 2
fi
: "${AGE_IDENTITY_FILE:?Set private age identity file (do not commit it)}"
BACKUP="$1"; CHECKSUM="$2"
if [[ ! -f "$BACKUP" || ! -f "$CHECKSUM" || ! -f "$AGE_IDENTITY_FILE" ]]; then
  echo "STOP: encrypted backup, checksum and key must exist" >&2; exit 2
fi
for executable in age docker openssl sha256sum; do
  command -v "$executable" >/dev/null || { echo "STOP: missing $executable" >&2; exit 2; }
done
( cd "$(dirname "$BACKUP")" && sha256sum -c "$CHECKSUM" )
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/../.."
PROJECT="sas-restore-drill-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 3)"
if [[ "$PROJECT" == sas-production || "$PROJECT" == sas-staging-shared ]]; then
  echo "STOP: invalid restore target" >&2; exit 2
fi
echo "Creating isolated restore target: $PROJECT"
docker compose --project-name "$PROJECT" --env-file "$DIR/.env" \
  -f "$DIR/compose.production.yaml" up -d --wait db
# Decrypt only into pg_restore stdin. A live database/volume is never targeted.
age -d -i "$AGE_IDENTITY_FILE" "$BACKUP" \
  | docker compose --project-name "$PROJECT" --env-file "$DIR/.env" \
      -f "$DIR/compose.production.yaml" exec -T db \
      pg_restore -U sas_prod -d sas_production --no-owner --no-acl --exit-on-error
REVISION="$(docker compose --project-name "$PROJECT" --env-file "$DIR/.env" \
  -f "$DIR/compose.production.yaml" exec -T db \
  psql -U sas_prod -d sas_production -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
if [[ -z "$REVISION" ]]; then
  echo "RESTORE INCOMPLETE: no Alembic revision found" >&2; exit 1
fi
echo "Restore completed in a SEPARATE named project (schema revision present)."
echo "Preserve target $PROJECT for a read-only finance/tenant integrity review."
echo "Never remove its volume before recording reviewer acceptance."
