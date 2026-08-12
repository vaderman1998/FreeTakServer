#!/usr/bin/env python3
"""Build the data package a TAK client needs to enrol with this server.

A client enrolling has no certificate yet, so it has to trust the server's
before it will talk to it. A server whose certificate came from a public
authority is trusted already; this one signs its own, so the client is given
the authority to trust, and told to enrol against it.

The package therefore carries no client certificate at all: only the
authority, and a connection set to enrol. On import the client asks for a
username and password, collects a certificate of its own, and comes up as
whichever user those credentials belong to.

    python3 make_enrollment_package.py 192.168.50.169
    python3 make_enrollment_package.py tak.example.org -o enroll.zip
"""
import argparse
import sys
import zipfile
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives.serialization import pkcs12  # noqa: E402

from FreeTAKServer.core.configuration.MainConfig import MainConfig  # noqa: E402
from FreeTAKServer.core.util.certificate_generation import _p12_encryption  # noqa: E402

config = MainConfig.instance()

# A client copies the files a package brings into its own certificate folder
# and looks for them there, by a path relative to it. This and the names below
# follow a working package from an official TAK server exactly, since the
# client is particular about all of it.
CLIENT_CERT_PATH = "cert"
TRUSTSTORE_NAME = "caCert.p12"
PREFERENCES_NAME = "config.pref"
MANIFEST_NAME = "MANIFEST.xml"
# the password an official server encrypts this store with, and so the one a
# client falls back to when it has none of its own recorded for the server
TRUSTSTORE_PASSWORD = "atakatak"


def build_truststore(ca_pem_path, password: str) -> bytes:
    """A store holding the authority a client should trust this server by.

    Built to match the store an official server hands out: the authority on
    its own, with no key and no certificate of the server's, so that a client
    reading it comes away with the authority and nothing else.
    """
    ca_certificate = x509.load_pem_x509_certificate(Path(ca_pem_path).read_bytes())
    return pkcs12.serialize_key_and_certificates(
        name=b"caCert",
        key=None,
        cert=None,
        cas=[ca_certificate],
        # TAK clients cannot read a modern AES encrypted store
        encryption_algorithm=_p12_encryption(password.encode()),
    )


def build_preferences(host: str, port: int, truststore_name: str, password: str,
                      enrollment_port: int) -> str:
    """The connection a client should create, set to enrol for a certificate."""
    return f"""<?xml version='1.0' encoding='ASCII' standalone='yes'?>
<preferences>
<preference version="1" name="cot_streams">
    <entry key="count" class="class java.lang.Integer">1</entry>
    <entry key="description0" class="class java.lang.String">FreeTAKServer_{host}</entry>
    <entry key="enabled0" class="class java.lang.Boolean">true</entry>
    <entry key="connectString0" class="class java.lang.String">{host}:{port}:ssl</entry>
    <entry key="caLocation0" class="class java.lang.String">{CLIENT_CERT_PATH}/{truststore_name}</entry>
    <entry key="caPassword0" class="class java.lang.String">{password}</entry>
    <entry key="enrollForCertificateWithTrust0" class="class java.lang.Boolean">true</entry>
    <entry key="useAuth0" class="class java.lang.Boolean">true</entry>
    <entry key="cacheCreds0" class="class java.lang.String">Cache credentials</entry>
</preference>
<preference version="1" name="com.atakmap.app_preferences">
    <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
    <entry key="apiCertEnrollmentPort" class="class java.lang.String">{enrollment_port}</entry>
</preference>
</preferences>
"""


def build_manifest(package_uid: str, name: str, truststore_name: str) -> str:
    return f"""<MissionPackageManifest version="2">
<Configuration>
    <Parameter name="uid" value="{package_uid}"/>
    <Parameter name="name" value="{name}"/>
    <Parameter name="onReceiveDelete" value="true"/>
</Configuration>
<Contents>
    <Content ignore="false" zipEntry="{PREFERENCES_NAME}"/>
    <Content ignore="false" zipEntry="{truststore_name}"/>
</Contents>
</MissionPackageManifest>
"""


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("host", help="the address clients reach this server on")
    parser.add_argument("-p", "--port", type=int, default=config.SSLCoTServicePort,
                        help="the CoT port clients connect to (default: %(default)s)")
    parser.add_argument("-o", "--output", help="file to write (default: enrollment-<host>.zip)")
    parser.add_argument("--password", default=TRUSTSTORE_PASSWORD,
                        help="password for the truststore (default: %(default)s, what TAK clients expect)")
    arguments = parser.parse_args()

    output = arguments.output or f"enrollment-{arguments.host.replace('.', '-')}.zip"

    try:
        truststore = build_truststore(config.CA, arguments.password)
    except FileNotFoundError:
        parser.error(f"no certificate authority found at {config.CA}")

    # named and laid out as a working package from an official server is: the
    # manifest naming the files exactly as they are stored, at the root
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(MANIFEST_NAME, build_manifest(
            str(uuid4()), f"FreeTAKServer enrollment {arguments.host}", TRUSTSTORE_NAME))
        package.writestr(PREFERENCES_NAME, build_preferences(
            arguments.host, arguments.port, TRUSTSTORE_NAME, arguments.password,
            int(config.CertificateEnrollmentPort)))
        package.writestr(TRUSTSTORE_NAME, truststore)

    print(f"wrote {output}")
    print(f"  server      {arguments.host}:{arguments.port}")
    print(f"  enrolling   {arguments.host}:{config.CertificateEnrollmentPort}")
    print("\nImport it in ATAK, then enter the username and password of a system user.")
    print("The client collects its own certificate and comes up on that user's channels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
