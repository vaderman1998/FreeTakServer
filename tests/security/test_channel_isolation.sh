#!/usr/bin/env bash
# Verify CoT channel segregation over the SSL CoT service.
#
# Certificates bind a client to a system user, whose channel membership
# decides who its traffic reaches. Three clients are used: two on channel
# "alpha" and one on channel "bravo". Traffic from an alpha client must
# reach the other alpha client and must never reach the bravo client.
set -uo pipefail

VENV=${VENV:-/root/FreeTakServer/.venv}
CERTS=${CERTS:-/opt/fts/certs}
PORT=${PORT:-8089}
HOST=${HOST:-127.0.0.1}

"$VENV/bin/python" - "$CERTS" "$HOST" "$PORT" <<'PYEOF'
import socket
import ssl
import sys
import time
import uuid

certs, host, port = sys.argv[1], sys.argv[2], int(sys.argv[3])

COT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<event version="2.0" uid="{uid}" type="a-f-G-U-C" how="m-g"'
    ' time="{t}" start="{t}" stale="{stale}">'
    '<point lat="45.0" lon="-93.0" hae="0.0" ce="9999999.0" le="9999999.0"/>'
    '<detail><contact callsign="{cs}"/><__group name="Cyan" role="Team Member"/></detail>'
    "</event>"
)


def ts(offset=0):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset))


def connect(cert_name, callsign):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(f"{certs}/{cert_name}.pem", f"{certs}/{cert_name}.key")
    sock = ctx.wrap_socket(socket.create_connection((host, port), timeout=15))
    sock.sendall(COT.format(uid=f"UID-{callsign}-{uuid.uuid4().hex[:6]}",
                            t=ts(), stale=ts(300), cs=callsign).encode())
    return sock


def drain(sock, seconds):
    sock.settimeout(seconds)
    buf = b""
    end = time.time() + seconds
    while time.time() < end:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
        except (socket.timeout, ssl.SSLError):
            break
    return buf


alpha1 = connect("chan-alpha-one", "ALPHA1")
alpha2 = connect("chan-alpha-two", "ALPHA2")
bravo1 = connect("chan-bravo-one", "BRAVO1")
time.sleep(4)
for s in (alpha1, alpha2, bravo1):
    drain(s, 2)

marker = f"CHANTEST-{uuid.uuid4().hex[:8]}"
alpha1.sendall(COT.format(uid=marker, t=ts(), stale=ts(300), cs="ALPHA1").encode())

same_channel = drain(alpha2, 10)
other_channel = drain(bravo1, 6)

for s in (alpha1, alpha2, bravo1):
    s.close()

ok = True
if marker.encode() in same_channel:
    print(f"PASS: same-channel client received {marker}")
else:
    print(f"FAIL: same-channel client did NOT receive {marker}")
    ok = False

if marker.encode() in other_channel:
    print(f"FAIL: other-channel client LEAKED {marker}")
    ok = False
else:
    print("PASS: other-channel client did not receive the message")

sys.exit(0 if ok else 1)
PYEOF
