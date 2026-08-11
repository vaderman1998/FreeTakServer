"""Move a connected client into another channel and confirm routing follows."""
import socket, ssl, sys, time, uuid
sys.path.insert(0, "/root/FreeTakServer")
from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

CERTS, HOST, PORT = "/opt/fts/certs", "127.0.0.1", 8089
COT = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
       '<event version="2.0" uid="{uid}" type="a-f-G-U-C" how="m-g" time="{t}" start="{t}" stale="{s}">'
       '<point lat="45.0" lon="-93.0" hae="0.0" ce="9999999.0" le="9999999.0"/>'
       '<detail><contact callsign="{cs}"/></detail></event>')

def ts(o=0): return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()+o))

def connect(name, cs):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(f"{CERTS}/{name}.pem", f"{CERTS}/{name}.key")
    s = ctx.wrap_socket(socket.create_connection((HOST, PORT), timeout=15))
    s.sendall(COT.format(uid=f"UID-{cs}-{uuid.uuid4().hex[:6]}", t=ts(), s=ts(300), cs=cs).encode())
    return s

def drain(s, secs):
    s.settimeout(secs); buf=b""; end=time.time()+secs
    while time.time() < end:
        try:
            c = s.recv(65536)
            if not c: break
            buf += c
        except (socket.timeout, ssl.SSLError): break
    return buf

from FreeTAKServer.core.util.certificate_generation import AtakOfTheCerts

db = DatabaseController()
# provision the fixtures so the test does not depend on leftover data
for fixture, channel in [("chan-alpha-one", "alpha"), ("chan-bravo-one", "bravo")]:
    if not db.query_systemUser(query=f'name = "{fixture}"'):
        db.create_systemUser(name=fixture, group="user", token=f"tok-{fixture}",
                             password="x", uid=str(uuid.uuid4()),
                             device_type="mobile", channels=channel)
    AtakOfTheCerts().bake(common_name=fixture, cert="user")

# start bravo-one on bravo, alpha-one on alpha: they must not see each other
db.update_systemUser(query='name = "chan-bravo-one"', column_value={"channels": "bravo"})
time.sleep(1)
a = connect("chan-alpha-one", "ALPHA1"); b = connect("chan-bravo-one", "BRAVO1")
time.sleep(4); drain(a,2); drain(b,2)

m1 = f"BEFORE-{uuid.uuid4().hex[:8]}"
a.sendall(COT.format(uid=m1, t=ts(), s=ts(300), cs="ALPHA1").encode())
isolated = m1.encode() not in drain(b, 8)
print(("PASS" if isolated else "FAIL") + ": different channels are isolated")

# now move bravo-one into alpha WITHOUT reconnecting
db.update_systemUser(query='name = "chan-bravo-one"', column_value={"channels": "alpha"})
print("moved chan-bravo-one to alpha; waiting for refresh...")
time.sleep(25)
drain(a,2); drain(b,2)

m2 = f"AFTER-{uuid.uuid4().hex[:8]}"
a.sendall(COT.format(uid=m2, t=ts(), s=ts(300), cs="ALPHA1").encode())
joined = m2.encode() in drain(b, 12)
print(("PASS" if joined else "FAIL") + ": reassignment applied without reconnect")

a.close(); b.close()
db.update_systemUser(query='name = "chan-bravo-one"', column_value={"channels": "bravo"})
sys.exit(0 if (isolated and joined) else 1)
