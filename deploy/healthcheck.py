"""Container healthcheck for a TLS-terminating Northbound deployment.

The image's baked-in HEALTHCHECK probes ``http://localhost:8090/health``. When
the app terminates TLS itself (``uvicorn --ssl-certfile``), that plain-HTTP
probe fails the handshake and Docker reports the container unhealthy while the
app is in fact serving 200s. This probe speaks HTTPS and pins the local CA.

Mounted into the container at /etc/northbound/healthcheck.py and wired up by
docker-compose.prod.yml.
"""

import ssl
import sys
import urllib.request

CA = "/etc/northbound/tls/root_ca.crt"
URL = "https://localhost:8090/health"

try:
    ctx = ssl.create_default_context(cafile=CA)
    with urllib.request.urlopen(URL, context=ctx, timeout=5) as resp:
        sys.exit(0 if resp.status == 200 else 1)
except Exception as exc:  # noqa: BLE001 - any failure means unhealthy
    print(f"healthcheck failed: {exc}", file=sys.stderr)
    sys.exit(1)
