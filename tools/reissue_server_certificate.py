#!/usr/bin/env python3
"""Reissue this server's certificate with the addresses clients reach it on.

The certificate this server has always presented names itself only in its
common name, and carries no subject alternative name at all. Clients stopped
accepting a name given that way years ago, so a client checking who it is
talking to finds nothing it can match and refuses, however well it trusts the
authority that signed it. A client with a certificate of its own never
noticed, because it was never asked to check.

The new certificate is signed by the same authority as before, so everything
that already trusts this server keeps trusting it, and the private key is
kept, so nothing else has to be reissued alongside it.

    python3 reissue_server_certificate.py 192.168.50.169
    python3 reissue_server_certificate.py 192.168.50.169 tak.example.org
"""
import argparse
import ipaddress
import random
import shutil
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from FreeTAKServer.core.configuration.MainConfig import MainConfig  # noqa: E402

config = MainConfig.instance()


def subject_alternative_names(addresses):
    """What the certificate should say this server answers to."""
    names = []
    for address in addresses:
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(address)))
        except ValueError:
            names.append(x509.DNSName(address))
    return names


def reissue(addresses, expiry_time_secs, pem_path, key_path, ca_pem_path, ca_key_path):
    key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    ca_key = serialization.load_pem_private_key(Path(ca_key_path).read_bytes(), password=None)
    ca_certificate = x509.load_pem_x509_certificate(Path(ca_pem_path).read_bytes())

    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, addresses[0]),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FreeTAKServer"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Core Dev"),
        ]))
        .issuer_name(ca_certificate.subject)
        .serial_number(random.getrandbits(64))
        .not_valid_before(now)
        .not_valid_after(now + timedelta(seconds=expiry_time_secs))
        .public_key(key.public_key())
        .add_extension(x509.SubjectAlternativeName(subject_alternative_names(addresses)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("address", nargs="*",
                        help="every address clients reach this server on (default: the configured one)")
    parser.add_argument("--days", type=int, default=825, help="how long it is valid (default: %(default)s)")
    arguments = parser.parse_args()

    addresses = list(arguments.address) or [str(config.UserConnectionIP)]
    # a server is reached from itself as well, and by name as well as address
    for extra in (socket.gethostname(), "localhost", "127.0.0.1"):
        if extra not in addresses:
            addresses.append(extra)

    pem_path = Path(str(config.pemDir))
    backup = pem_path.with_suffix(".pem.before-san")
    if not backup.exists():
        shutil.copy2(pem_path, backup)
        print(f"kept the previous certificate as {backup}")

    pem = reissue(
        addresses,
        arguments.days * 24 * 60 * 60,
        pem_path,
        str(config.unencryptedKey),
        str(config.CA),
        str(config.CAkey),
    )
    pem_path.write_bytes(pem)

    print(f"wrote {pem_path}")
    print(f"  answers to  {', '.join(addresses)}")
    print(f"  valid for   {arguments.days} days")
    print("\nRestart the server for it to be served: systemctl restart fts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
