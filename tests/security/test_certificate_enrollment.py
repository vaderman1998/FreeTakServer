"""A client can join with a username and password.

Walks the exchange a TAK client performs when it enrolls: ask how the
certificate authority names things, send a certificate request to be signed,
then collect the profile of settings to apply. The signed certificate has to
be usable against the server's CoT port afterwards, otherwise the client has
enrolled into something it cannot connect to.

Usage: python3 test_certificate_enrollment.py [host]
"""
import base64
import io
import json
import socket
import ssl
import sqlite3
import sys
import urllib.error
import urllib.request
import zipfile
from xml.etree.ElementTree import fromstring

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
ENROLLMENT = f"https://{HOST}:8446"
SSL_COT_PORT = 8089
FTS_DB = "/opt/fts/FTSDataBase.db"

USERNAME = "enroll-probe"
PASSWORD = "enroll-probe-pass"
USER_ID = "3c9a77e1-0000-4000-8000-enrollmentprobe"
CLIENT_UID = "ENROLL-PROBE-DEVICE"

failures = []


def check(condition, message):
    print(("PASS: " if condition else "FAIL: ") + message)
    if not condition:
        failures.append(message)


def call(path, method="GET", body=None, credentials=(USERNAME, PASSWORD), accept=None):
    request = urllib.request.Request(f"{ENROLLMENT}{path}", method=method)
    if credentials:
        token = base64.b64encode(":".join(credentials).encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    if accept:
        request.add_header("Accept", accept)
    if body is not None:
        request.data = body
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


database = sqlite3.connect(FTS_DB)
database.execute(
    "insert or replace into SystemUser (uid, name, token, password, device_type, channels)"
    " values (?,?,?,?,?,?)",
    (USER_ID, USERNAME, "enroll-probe-token", PASSWORD, "mobile", "alpha"),
)
database.commit()
database.close()

# the credentials have to be checked
status, _ = call("/Marti/api/tls/config", credentials=None)
check(status == 401, "enrolling without credentials is refused")
status, _ = call("/Marti/api/tls/config", credentials=(USERNAME, "wrong-password"))
check(status == 401, "enrolling with the wrong password is refused")

# how the certificate authority names things
status, body = call("/Marti/api/tls/config")
check(status == 200, "the certificate authority configuration is served")
if status == 200:
    root = fromstring(body)
    # the document declares a default namespace, so the tags come back
    # qualified with it and are matched on their local name
    names = {
        entry.get("name"): entry.get("value")
        for entry in root.iter()
        if entry.tag.rsplit("}", 1)[-1] == "nameEntry"
    }
    check(
        "O" in names and "OU" in names,
        f"the configuration names the organisation and unit (got {names})",
    )

# a certificate request, as a client generates for itself
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
csr = (
    x509.CertificateSigningRequestBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, USERNAME)]))
    .sign(key, hashes.SHA256())
)
csr_pem = csr.public_bytes(serialization.Encoding.PEM)
# clients send it without the header, footer or line breaks
csr_body = "".join(
    line for line in csr_pem.decode().splitlines() if not line.startswith("-----")
).encode()

status, body = call(f"/Marti/api/tls/signClient/v2?clientUid={CLIENT_UID}", "POST", csr_body)
check(status == 200, f"a certificate request is signed (got {status})")

signed_certificate = None
if status == 200:
    payload = json.loads(body)
    check(
        {"signedCert", "ca0"} <= set(payload),
        f"the response carries the signed certificate and the authority (got {list(payload)})",
    )
    signed_certificate = (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(payload["signedCert"][i:i + 64] for i in range(0, len(payload["signedCert"]), 64))
        + "\n-----END CERTIFICATE-----\n"
    )
    certificate = x509.load_pem_x509_certificate(signed_certificate.encode())
    common_name = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    check(common_name == USERNAME, f"the certificate is issued to the name asked for (got {common_name})")

    ca_pem = (
        "-----BEGIN CERTIFICATE-----\n"
        + "\n".join(payload["ca0"][i:i + 64] for i in range(0, len(payload["ca0"]), 64))
        + "\n-----END CERTIFICATE-----\n"
    )
    authority = x509.load_pem_x509_certificate(ca_pem.encode())
    check(
        certificate.issuer == authority.subject,
        "the certificate was signed by the authority the server returned",
    )

# the profile of settings the client applies afterwards
status, body = call(f"/Marti/api/tls/profile/enrollment?clientUid={CLIENT_UID}")
check(status == 200, f"the enrollment profile is served (got {status})")
if status == 200:
    package = zipfile.ZipFile(io.BytesIO(body))
    names = package.namelist()
    check(any(name.endswith("preference.pref") for name in names), f"the profile carries preferences (got {names})")
    check(any("manifest" in name.lower() for name in names), "the profile carries a manifest")

    preferences = package.read(next(n for n in names if n.endswith("preference.pref"))).decode()
    entries = {
        entry.get("key"): entry.text for entry in fromstring(preferences).iter("entry")
    }
    check(entries.get("prefs_enable_channels") == "true", "the profile switches the channel list on")
    check(
        entries.get(f"prefs_enable_channels_host-{HOST}") == "true",
        f"the profile switches the channel list on for this server (got {list(entries)})",
    )

# the certificate has to actually work against the CoT port
if signed_certificate:
    import tempfile, os

    certificate_file = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    certificate_file.write(signed_certificate)
    certificate_file.close()
    key_file = tempfile.NamedTemporaryFile("wb", suffix=".key", delete=False)
    key_file.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    key_file.close()

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        context.load_cert_chain(certificate_file.name, key_file.name)
        connection = context.wrap_socket(socket.create_connection((HOST, SSL_COT_PORT), timeout=20))
        connection.close()
        check(True, "the issued certificate is accepted by the CoT port")
    except Exception as error:
        check(False, f"the issued certificate is accepted by the CoT port ({error})")
    finally:
        os.unlink(certificate_file.name)
        os.unlink(key_file.name)

database = sqlite3.connect(FTS_DB)
database.execute("delete from SystemUser where uid = ?", (USER_ID,))
database.commit()
database.close()

print(f"\nRESULT: {len(failures)} failed")
sys.exit(1 if failures else 0)
