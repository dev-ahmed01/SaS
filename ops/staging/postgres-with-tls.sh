#!/bin/sh
set -eu
# The key is 0600 on the VPS and mounted read-only. This root-only setup step
# installs a private PostgreSQL-owned copy; the official entrypoint then drops
# privileges to the postgres user.
if [ "$(id -u)" = "0" ]; then
    install -o postgres -g postgres -m 600 /run/postgres-tls/server.key /var/lib/postgresql/server.key
    install -o postgres -g postgres -m 644 /run/postgres-tls/server.crt /var/lib/postgresql/server.crt
fi
exec /usr/local/bin/docker-entrypoint.sh "$@"
