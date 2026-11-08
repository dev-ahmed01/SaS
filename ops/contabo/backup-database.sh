#!/usr/bin/env bash
# Stream an encrypted logical backup. Never writes an unencrypted dump to disk.
set -euo pipefail
umask 077
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR/../.."

: "${SAS_BACKUP_AGE_RECIPIENT:?Set the approved age public recipient key (age1...)}"
if [[ ! "$SAS_BACKUP_AGE_RECIPIENT" =~ ^age1[a-z0-9]{20,}$ ]]; then
  echo "STOP: recipient must be a valid age1... public key" >&2; exit 2
fi
for executable in age docker sha256sum; do
  command -v "$executable" >/dev/null || { echo "STOP: missing $executable" >&2; exit 2; }
done
OUTPUT_DIR="${SAS_BACKUP_DIR:-$DIR/backups}"
mkdir -p "$OUTPUT_DIR"
chmod 700 "$OUTPUT_DIR"
OUT="$OUTPUT_DIR/sas-$(date -u +%Y%m%dT%H%M%SZ).dump.age"
if [[ -e "$OUT" ]]; then
  echo "STOP: backup name already exists" >&2; exit 2
fi
TEMP="$OUT.partial"
trap 'rm -f "$TEMP"' EXIT
docker compose --env-file "$DIR/.env" -f "$DIR/compose.production.yaml" \
  exec -T db pg_dump -U sas_prod -d sas_production -Fc --no-owner --no-acl \
  | age -r "$SAS_BACKUP_AGE_RECIPIENT" -o "$TEMP"
test -s "$TEMP"
chmod 600 "$TEMP"
mv "$TEMP" "$OUT"
( cd "$OUTPUT_DIR" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
chmod 600 "$OUT.sha256"
trap - EXIT
echo "Encrypted, checksummed SaS backup created at: $OUT"
echo "Copy this file and checksum to independent off-host storage; perform a restore drill."
