# !/usr/bin/python
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from datetime import datetime, timedelta, timezone
import os
import getopt
import sys
import random
from shutil import copyfile
import uuid
from jinja2 import Template
import socket
import zipfile
import shutil
import pathlib
from FreeTAKServer.core.configuration.MainConfig import MainConfig
from werkzeug.utils import secure_filename

import requests
import hashlib

# Make a connection to the MainConfig object for all routines below
config = MainConfig.instance()

def _fts_x509_name(common_name: str) -> x509.Name:
    """The subject/issuer name FTS has always stamped on its certificates."""
    return x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Nova Scotia"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "FreeTAKServer"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Core Dev"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Halifax"),
    ])


def sign_certificate_request(csr_pem: bytes, expiry_time_secs: int = 31536000,
                             ca_pem_path=config.CA, ca_key_path=config.CAkey):
    """Sign a client's certificate request with this server's CA.

    A client enrolling with the server keeps its own private key and sends
    only the request, so unlike the certificates baked here there is no key
    to hand back. The subject is taken from the request, since the client
    chose the name it wants to be known by.

    Returns the signed certificate and the CA certificate, both PEM encoded.
    """
    csr = x509.load_pem_x509_csr(csr_pem)
    if not csr.is_signature_valid:
        raise ValueError("the certificate request is not correctly signed")

    ca_key = serialization.load_pem_private_key(open(ca_key_path, "rb").read(), password=None)
    ca_cert = x509.load_pem_x509_certificate(open(ca_pem_path, "rb").read())

    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(csr.subject)
        .issuer_name(ca_cert.subject)
        .serial_number(random.getrandbits(64))
        .not_valid_before(now)
        .not_valid_after(now + timedelta(seconds=expiry_time_secs))
        .public_key(csr.public_key())
        .sign(ca_key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM),
        ca_cert.public_bytes(serialization.Encoding.PEM),
    )


def certificate_request_common_name(csr_pem: bytes):
    """The common name a certificate request asks for."""
    csr = x509.load_pem_x509_csr(csr_pem)
    for attribute in csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME):
        return attribute.value
    return None


def _subject_alternative_names(addresses):
    """The addresses a certificate says its holder answers to."""
    import ipaddress

    names = []
    for address in addresses:
        if not address:
            continue
        try:
            names.append(x509.IPAddress(ipaddress.ip_address(str(address))))
        except ValueError:
            names.append(x509.DNSName(str(address)))
    return names


def _p12_encryption(password: bytes):
    # TAK clients (ATAK/iTAK/WinTAK) expect the legacy PKCS12 encryption that
    # OpenSSL 1.1.x produced (SHA1 + 3DES); modern AES-256 defaults are not
    # accepted by all client versions, so keep emitting the legacy format.
    return (
        serialization.PrivateFormat.PKCS12.encryption_builder()
        .kdf_rounds(50000)
        .key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC)
        .hmac_hash(hashes.SHA1())
        .build(password)
    )



# the password TAK clients fall back to for a store they have nothing recorded for
TRUSTSTORE_PASSWORD = "atakatak"


def build_ca_truststore(password: str = TRUSTSTORE_PASSWORD, ca_pem_path=None) -> bytes:
    """A store holding this server's authority, for clients to trust it by.

    Holding the authority rather than a certificate of the server's means a
    client keeps working when the server's own certificate is reissued, and
    means the server's key is not handed to every client that connects.

    The authority is named, because a client lists what a store holds by the
    names inside it and passes over anything unnamed.
    """
    from cryptography.hazmat.primitives.serialization.pkcs12 import PKCS12Certificate

    ca_certificate = x509.load_pem_x509_certificate(
        open(ca_pem_path or config.CA, "rb").read()
    )
    return pkcs12.serialize_key_and_certificates(
        name=None,
        key=None,
        cert=None,
        cas=[PKCS12Certificate(ca_certificate, b"caCert")],
        encryption_algorithm=_p12_encryption(password.encode()),
    )


def _sign_crl(revoked_certs, ca_cert, ca_private_key):
    """Build and sign a CRL containing the given revoked certificates."""
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(ca_cert.subject)
        .last_update(now)
        .next_update(now + timedelta(days=100))
    )
    for revoked in revoked_certs:
        builder = builder.add_revoked_certificate(revoked)
    return builder.sign(private_key=ca_private_key, algorithm=hashes.SHA256())


def _replace_crl_in_pem(pem_path, crl_pem_bytes):
    """Strip any CRL block from the end of a PEM file and append a new one."""
    delete = 0
    with open(pem_path, "r") as f:
        lines = f.readlines()
    with open(pem_path, "w") as f:
        for line in lines:
            if delete:
                continue
            elif line.strip("\n") != "-----BEGIN X509 CRL-----":
                f.write(line)
            else:
                delete = 1
    with open(pem_path, "ab") as f:
        f.write(crl_pem_bytes)


def revoke_certificate(username, revoked_file=None, ca_pem = config.CA, ca_key = config.CAkey, crl_file = config.CRLFile, user_cert_dir=config.certsPath, crl_path=config.CRLFile):
    """
    Function to create/update a CRL with revoked user certificates
    :param ca_pem: The path to your CA PEM file
    :param ca_key: The Path to your CA key file
    :param revoked_file: Path to JSON file to be used as a DB for revocation
    :param crl_file: Path to CRL file
    :param user_cert_dir: Path to director containing all issued user PEM files
    :param username: the username to Revoke
    :param crl_path: The path to your previous CRL file to be loaded and updated
    :return: bool
    """

    import os
    import json

    data = {}
    certificate = x509.load_pem_x509_certificate(open(ca_pem, mode="rb").read())
    private_key = serialization.load_pem_private_key(
        open(ca_key, mode="rb").read(), password=None
    )
    existing_revocations = []
    if crl_path and os.path.exists(crl_path):
        existing_crl = x509.load_pem_x509_crl(open(crl_path, mode="rb").read())
        existing_revocations = list(existing_crl)
    elif revoked_file and os.path.exists(revoked_file):
        with open(revoked_file, 'r') as json_file:
            data = json.load(json_file)

    for cert in os.listdir(user_cert_dir):
        if cert.lower() == f"{username.lower()}.pem":
            with open(config.certsPath+'/'+cert, 'rb') as cert:
                revoked_cert = x509.load_pem_x509_certificate(cert.read())
            data[str(revoked_cert.serial_number)] = username
            break

    now = datetime.now(timezone.utc)
    new_revocations = [
        x509.RevokedCertificateBuilder()
        .serial_number(int(key))
        .revocation_date(now)
        .build()
        for key in data
    ]
    crl = _sign_crl(existing_revocations + new_revocations, certificate, private_key)
    if revoked_file:
        with open(revoked_file, 'w+') as json_file:
            json.dump(data, json_file)

    crl_pem = crl.public_bytes(serialization.Encoding.PEM)
    with open(crl_file, 'wb') as f:
        f.write(crl_pem)

    _replace_crl_in_pem(ca_pem, crl_pem)


def send_data_package(server: str, dp_name: str = "user.zip") -> bool:
    """
    Function to send data package to server
    :param server: Server address where the package will be uploaded
    :param dp_name: Name of the zip file to upload
    :return: bool
    """
    file_hash = hashlib.sha256()
    block_size = 65536
    with open(dp_name, 'rb') as f:
        fb = f.read(block_size)
        while len(fb) > 0:
            file_hash.update(fb)
            fb = f.read(block_size)

    with open(dp_name, 'rb') as f:
        s = requests.Session()
        r = s.post(f'http://{server}:8080/Marti/sync/missionupload?hash={file_hash.hexdigest()}'
                   f'&filename={dp_name}'
                   f'&creatorUid=atakofthecerts',
                   files={"assetfile": f.read()},
                   headers={'Expect': '100-continue'})
        if r.status_code == 200:
            p_r = s.put(f'http://{server}:8080/Marti/api/sync/metadata/{file_hash.hexdigest()}/tool')
            return True
        else:
            print("Something went wrong uploading DataPackage!")
            return False

def generate_standard_zip(server_address: str = None, server_filename: str = "", user_filename: str = "Client.p12",
                 cert_password: str = config.password, ssl_port: str = "8089") -> None:
    """
    A Function to generate a Client connection Data Package (DP) from a server and user p12 file in the current
    working directory.
    :param server_address: A string based ip address or FQDN that clients will use to connect to the server
    :param server_filename: The filename of the server p12 file default is pubserver.p12
    :param user_filename: The filename of the server p12 file default is user.p12
    :param cert_password: The password for the certificate files
    :param ssl_port: The port used for SSL CoT, defaults to 8089
    """
    if server_filename == "":
        server_filename = config.UserConnectionIP.replace(".", "-")+"_"+config.version.replace(".","-")+"_"+config.nodeID+".p12"

    pref_file_template = Template("""<?xml version='1.0' encoding='ASCII' standalone='yes'?>
    <preferences>
        <preference version="1" name="cot_streams">
            <entry key="count" class="class java.lang.Integer">1</entry>
            <entry key="description0" class="class java.lang.String">FreeTAKServer_{{ server }}</entry>
            <entry key="enabled0" class="class java.lang.Boolean">false</entry>
            <entry key="connectString0" class="class java.lang.String">{{ server }}:{{ port }}:ssl</entry>
        </preference>
        <preference version="1" name="com.atakmap.app_preferences">
            <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
            <entry key="caLocation" class="class java.lang.String">/cert/{{ server_filename }}</entry>
            <entry key="caPassword" class="class java.lang.String">{{ truststore_password }}</entry>
            <entry key="clientPassword" class="class java.lang.String">{{ cert_password }}</entry>
            <entry key="certificateLocation" class="class java.lang.String">/cert/{{ user_filename }}</entry>
            <entry key="prefs_enable_channels" class="class java.lang.String">true</entry>
            <entry key="prefs_enable_channels_host-{{ server }}" class="class java.lang.String">true</entry>
        </preference>
    </preferences>
    """)

    manifest_file_template = Template("""<MissionPackageManifest version="2">
       <Configuration>
          <Parameter name="uid" value="{{ uid }}"/>
          <Parameter name="name" value="FreeTAKServer_{{ server }}"/>
          <Parameter name="onReceiveDelete" value="true"/>
       </Configuration>
       <Contents>
          <Content ignore="false" zipEntry="cert/fts.pref"/>
          <Content ignore="false" zipEntry="cert/{{ server_filename }}"/>
          <Content ignore="false" zipEntry="cert/{{ user_filename }}"/>
       </Contents>
    </MissionPackageManifest>
    """)

    username = user_filename[:-4]
    random_id = uuid.uuid4()
    if config.UserConnectionIP == "0.0.0.0":
        hostname = socket.gethostname()
        server_address = socket.gethostbyname(hostname)
    else:
        server_address = config.UserConnectionIP
    pref = pref_file_template.render(server=server_address, server_filename=server_filename,
                                     user_filename=user_filename, cert_password=cert_password,
                                     truststore_password=TRUSTSTORE_PASSWORD,
                                     port=str(config.SSLCoTServicePort))
    man = manifest_file_template.render(uid=random_id, server=server_address, server_filename=server_filename,
                                        user_filename=user_filename)
    with open('fts.pref', 'w') as pref_file:
        pref_file.write(pref)
    with open('manifest.xml', 'w') as manifest_file:
        manifest_file.write(man)
    with open(server_filename, 'wb') as truststore:
        truststore.write(build_ca_truststore())
    copyfile(pathlib.Path(config.certsPath, user_filename), pathlib.Path(user_filename))
    with zipfile.ZipFile(
        pathlib.PurePath(pathlib.Path(config.ClientPackages), pathlib.Path(f"{username}.zip")),
        mode='w',
        compresslevel=zipfile.ZIP_DEFLATED) as zipf:

        zipf.write('fts.pref')
        zipf.write('manifest.xml')
        zipf.write(user_filename)
        zipf.write(server_filename)


    os.remove('fts.pref')
    os.remove('manifest.xml')

def generate_wintak_zip(server_address: str = None, server_filename: str = "", user_filename: str = "Client.p12",
                 cert_password: str = config.password, ssl_port: str = "8089") -> None:
    """
    A Function to generate a Client connection Data Package (DP) from a server and user p12 file in the current
    working directory.
    :param server_address: A string based ip address or FQDN that clients will use to connect to the server
    :param server_filename: The filename of the server p12 file default is pubserver.p12
    :param user_filename: The filename of the server p12 file default is user.p12
    :param cert_password: The password for the certificate files
    :param ssl_port: The port used for SSL CoT, defaults to 8089
    """
    if server_filename == "":
        server_filename = config.UserConnectionIP.replace(".", "-")+"_"+config.version.replace(".","-")+"_"+config.nodeID+".p12"
    pref_file_template = Template("""<?xml version='1.0' standalone='yes'?>
    <preferences>
        <preference version="1" name="cot_streams">
            <entry key="count" class="class java.lang.Integer">1</entry>
            <entry key="description0" class="class java.lang.String">FreeTAKServer_{{ server }}</entry>
            <entry key="enabled0" class="class java.lang.Boolean">false</entry>
            <entry key="connectString0" class="class java.lang.String">{{ server }}:{{ port }}:ssl</entry>
        </preference>
        <preference version="1" name="com.atakmap.app_preferences">
            <entry key="displayServerConnectionWidget" class="class java.lang.Boolean">true</entry>
            <entry key="caLocation" class="class java.lang.String">/storage/emulated/0/atak/cert/{{ server_filename }}</entry>
            <entry key="caPassword" class="class java.lang.String">{{ truststore_password }}</entry>
            <entry key="clientPassword" class="class java.lang.String">{{ cert_password }}</entry>
            <entry key="certificateLocation" class="class java.lang.String">/storage/emulated/0/atak/cert/{{ user_filename }}</entry>
            <entry key="prefs_enable_channels" class="class java.lang.String">true</entry>
            <entry key="prefs_enable_channels_host-{{ server }}" class="class java.lang.String">true</entry>
        </preference>
    </preferences>
    """)

    manifest_file_template = Template("""<MissionPackageManifest version="2">
       <Configuration>
          <Parameter name="uid" value="{{ uid }}"/>
          <Parameter name="name" value="FreeTAKServer_{{ server }}"/>
          <Parameter name="onReceiveDelete" value="true"/>
       </Configuration>
       <Contents>
          <Content ignore="false" zipEntry="{{ folder }}/fts.pref"/>
          <Content ignore="false" zipEntry="{{ folder }}/{{ server_filename }}"/>
          <Content ignore="false" zipEntry="{{ folder }}/{{ user_filename }}"/>
       </Contents>
    </MissionPackageManifest>
    """)

    manifest_file_parent_template = Template("""<MissionPackageManifest version="2">
           <Configuration>
              <Parameter name="uid" value="{{ uid }}"/>
              <Parameter name="name" value="FreeTAKServer_{{ server }}_DP"/>
           </Configuration>
           <Contents>
              <Content ignore="false" zipEntry="{{ folder }}/{{ internal_dp_name }}.zip"/>
           </Contents>
        </MissionPackageManifest>
        """)
    username = secure_filename(user_filename[:-4])
    random_id = uuid.uuid4()
    new_uid = uuid.uuid4()
    folder = "5c2bfcae3d98c9f4d262172df99ebac5"
    parentfolder = "80b828699e074a239066d454a76284eb"
    if config.UserConnectionIP == "0.0.0.0":
        hostname = socket.gethostname()
        server_address = socket.gethostbyname(hostname)
    else:
        server_address = config.UserConnectionIP
    pref = pref_file_template.render(server=server_address, server_filename=server_filename,
                                     user_filename=user_filename, cert_password=cert_password,
                                     truststore_password=TRUSTSTORE_PASSWORD,
                                     port=str(config.SSLCoTServicePort))
    man = manifest_file_template.render(uid=random_id, server=server_address, server_filename=server_filename,
                                        user_filename=user_filename, folder=folder)
    man_parent = manifest_file_parent_template.render(uid=new_uid, server=server_address,
                                                      folder=parentfolder,
                                                      internal_dp_name=f"{username.replace('./', '')}")
    if not os.path.exists("./" + folder):
        os.makedirs("./" + folder)
    if not os.path.exists("./MANIFEST"):
        os.makedirs("./MANIFEST")
    with open('./' + folder + '/fts.pref', 'w') as pref_file:
        pref_file.write(pref)
    with open('./MANIFEST/manifest.xml', 'w') as manifest_file:
        manifest_file.write(man)
    with open("./" + folder + "/" + server_filename, "wb") as truststore:
        truststore.write(build_ca_truststore())
    copyfile(pathlib.Path(config.certsPath, user_filename), pathlib.Path(folder, user_filename))
    zipf = zipfile.ZipFile(f"{username}.zip", 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk('./' + folder):
        for file in files:
            zipf.write(os.path.join(root, file))
    for root, dirs, files in os.walk('./MANIFEST'):
        for file in files:
            zipf.write(os.path.join(root, file))
    zipf.close()
    shutil.rmtree("./MANIFEST")
    shutil.rmtree("./" + folder)
    # Create outer DP...because WinTAK
    if not os.path.exists("./" + parentfolder):
        os.makedirs("./" + parentfolder)
    if not os.path.exists("./MANIFEST"):
        os.makedirs("./MANIFEST")
    with open('./MANIFEST/manifest.xml', 'w') as manifest_parent:
        manifest_parent.write(man_parent)
    copyfile(f"{username}.zip", pathlib.Path(parentfolder, f"{username}.zip"))
    zipp = zipfile.ZipFile(str(pathlib.PurePath(pathlib.Path(config.ClientPackages), pathlib.Path(f"{username}.zip"))), 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk('./' + parentfolder):
        for file in files:
            name = str(pathlib.PurePath(pathlib.Path(root), pathlib.Path(file)))
            zipp.write(name)
    for root, dirs, files in os.walk('./MANIFEST'):
        for file in files:
            zipp.write(os.path.join(root, file))
    zipp.close()
    shutil.rmtree("./MANIFEST")
    shutil.rmtree("./" + parentfolder)
    os.remove(f"./{username}.zip")


class AtakOfTheCerts:
    def __init__(self, pwd: str = config.password) -> None:
        """
        :param pwd: String based password used to secure the p12 files generated, defaults to MainConfig.password
        """
        self.key = None
        self.CERTPWD = pwd
        self.cakeypath = config.CAkey
        self.capempath = config.CA

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return None

    def generate_ca(self, expiry_time_secs: int = 31536000) -> None:
        """
        Generate a CA certificate
        """
        if (pathlib.Path(config.certsPath, 'ca.key').exists()):
            print("CA found locally, not generating a new one")
            return

        print("Cannot find CA file locally so generating one")
        if not os.path.exists(config.certsPath):
            print("The directory for storing certificates doesn't exist.")
            print("Creating one at " + config.certsPath)
            os.makedirs(config.certsPath)
        serial_number = random.getrandbits(64)

        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = _fts_x509_name(str(random.getrandbits(64)))
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .serial_number(serial_number)
            .not_valid_before(now)
            .not_valid_after(now + timedelta(seconds=expiry_time_secs))
            .public_key(ca_key.public_key())
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=False)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False, content_commitment=False,
                    key_encipherment=False, data_encipherment=False,
                    key_agreement=False, key_cert_sign=True, crl_sign=True,
                    encipher_only=False, decipher_only=False,
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        with open(self.cakeypath, "wb") as f:
            f.write(ca_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            ))

        with open(self.capempath, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        # append empty crl
        crl = _sign_crl([], cert, ca_key)
        crl_pem = crl.public_bytes(serialization.Encoding.PEM)

        with open(config.CRLFile, 'wb') as f:
            f.write(crl_pem)

        _replace_crl_in_pem(self.capempath, crl_pem)

    def _generate_key(self, keypath: str) -> None:
        """
        Generate a new certificate key
        :param keypath: String based filepath to place new key, this should have a .key file extention
        """
        if os.path.exists(keypath):
            print("Certificate file exists, aborting.")
            # load the existing key so a subsequent _generate_certificate call
            # signs a certificate matching the key already on disk
            with open(keypath, "rb") as f:
                self.key = serialization.load_pem_private_key(f.read(), password=None)
        else:
            print("Generating Key...")
            self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            with open(keypath, "wb") as f:
                f.write(self.key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.TraditionalOpenSSL,
                    serialization.NoEncryption(),
                ))

    def _generate_certificate(self, common_name: str, p12path: str, pempath: str = config.pemDir,
                              expiry_time_secs: int = 31536000, server_addresses=None) -> None:
        """
        Create a certificate and p12 file
        :param cn: Common Name for certificate
        :param pempath: String filepath for the pem file created
        :param p12path: String filepath for the p12 file created
        :param expiry_time_secs: length of time in seconds that the certificate is valid for, defaults to 1 year
        """
        if not os.path.exists(pempath):
            ca_key = serialization.load_pem_private_key(
                open(self.cakeypath, "rb").read(), password=None
            )
            ca_pem = x509.load_pem_x509_certificate(open(self.capempath, 'rb').read())
            serial_number = random.getrandbits(64)
            now = datetime.now(timezone.utc)
            builder = (
                x509.CertificateBuilder()
                .subject_name(_fts_x509_name(common_name))
                .issuer_name(ca_pem.subject)
                .serial_number(serial_number)
                .not_valid_before(now)
                .not_valid_after(now + timedelta(seconds=expiry_time_secs))
                .public_key(self.key.public_key())
            )
            # a client checks who it is talking to against the names in the
            # certificate, and has not accepted a name given only as the
            # common name for years; without these it refuses the server
            if server_addresses:
                builder = builder.add_extension(
                    x509.SubjectAlternativeName(_subject_alternative_names(server_addresses)),
                    critical=False,
                )
            cert = builder.sign(ca_key, hashes.SHA256())
            p12data = pkcs12.serialize_key_and_certificates(
                name=common_name.encode("UTF-8"),
                key=self.key,
                cert=cert,
                cas=[ca_pem],
                encryption_algorithm=_p12_encryption(
                    bytes(self.CERTPWD, encoding='UTF-8')
                ),
            )
            with open(p12path, 'wb') as p12file:
                p12file.write(p12data)

            with open(pempath, "wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
        else:
            pass
    def bake(self, common_name: str, cert: str = "user", expiry_time_secs: int = 31536000) -> None:
        """
        Wrapper for creating certificate and all files needed
        :param common_name: Common Name of the the certificate
        :param cert: Type of cert being created "user" or "server"
        :param expiry_time_secs: length of time in seconds that the certificate is valid for, defaults to 1 year
        """
        keypath = pathlib.Path(config.certsPath,f"{common_name}.key")
        pempath = pathlib.Path(config.certsPath,f"{common_name}.pem")
        p12path = pathlib.Path(config.certsPath,f"{common_name}.p12")
        self._generate_key(keypath)
        server_addresses = None
        if cert.lower() == "server":
            # the addresses clients reach this server on, so they can check it
            server_addresses = [str(config.UserConnectionIP), socket.gethostname(), "localhost", "127.0.0.1"]
        self._generate_certificate(common_name=common_name, pempath=pempath, p12path=p12path,
                                   expiry_time_secs=expiry_time_secs, server_addresses=server_addresses)
        if cert.lower() == "server":
            copyfile(keypath, str(keypath) + ".unencrypted")

    @staticmethod
    def copy_server_certs(server_name: str = "server") -> None:
        """
        copy all the server files with of a given name to the FTS server cert location
        :param server_name: Name of the server/IP address that was used when generating the certificate
        """
        """python37_fts_path = MainConfig.MainPath
        python38_fts_path = MainConfig.MainPath
        if os.path.exists(python37_fts_path):
            dest = python37_fts_path
        elif os.path.exists(python38_fts_path):
            dest = python38_fts_path
        else:
            print("Cannot Find FreeTAKServer install location, cannot copy")
            return None
        if not os.path.exists(dest + "/Certs"):
            os.makedirs(dest + "/Certs")"""
        copyfile("./" + server_name + ".key", config.keyDir)
        copyfile("./" + server_name + ".key", config.unencryptedKey)
        copyfile("./" + server_name + ".pem", config.pemDir)

    def generate_auto_certs(self, ip: str, copy: bool = False, expiry_time_secs: int = 31536000, wintak_zip=False) -> None:
        """
        Generate the basic files needed for a new install of FTS
        :param ip: A string based ip address or FQDN that clients will use to connect to the server
        :param copy: Whether to copy server files to FTS expected locations
        :param expiry_time_secs: length of time in seconds that the certificate is valid for, defaults to 1 year
        """
        self.bake("server", "server", expiry_time_secs)
        self.bake("Client", "user", expiry_time_secs)
        if copy is True:
            self.copy_server_certs()
        if wintak_zip:
            generate_wintak_zip(server_address=ip)
        else:
            generate_standard_zip(server_address=ip)