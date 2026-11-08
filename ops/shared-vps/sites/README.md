# Optional dashboard hostnames

SaS starts on the shared Caddy gateway without WE/AE hostnames. Only after a
dashboard is deployed and its DNS is correct, copy the corresponding site block
from `other-dashboards.example` into a `.caddy` file in this directory and
set its hostname in the gateway's private environment file.

The shared proxy must connect to `emlen_ingress`, where `we-web` and
`ae-web` are reachable. Keep staging `noindex`. A route being present does
not mean the app's private database or media storage is deployed.
