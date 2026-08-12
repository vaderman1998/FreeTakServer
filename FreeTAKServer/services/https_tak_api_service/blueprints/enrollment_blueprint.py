"""Certificate enrollment, so a client can join with a username and password.

A TAK client that enrolls asks the server to sign a certificate it generated
itself, then asks for a profile of settings to apply. Without this a client
can only be added by building a data package for it by hand, and never
receives the settings the profile carries, among them the ones that make its
channel list work at all.

The client does this on its own port, authenticating with a username and
password rather than a certificate it does not have yet.
"""
import base64
import binascii
import io
import uuid
import zipfile
from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, Response, request

from FreeTAKServer.core.configuration.MainConfig import MainConfig
from FreeTAKServer.core.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.core.configuration.CreateLoggerController import CreateLoggerController
from FreeTAKServer.core.util import certificate_generation

logger = CreateLoggerController("FTS-Enrollment", logging_constants=LoggingConstants()).getLogger()

config = MainConfig.instance()
page = Blueprint("enrollment", __name__)

# the folder name a TAK client unpacks a mission package into
PROFILE_FOLDER = "5c2bfcae3d98c9f4d262172df99ebac5"


def _authenticated_user():
    """The system user named by the request's credentials, if they are right.

    Passwords are held in the clear by this server, as everything else that
    checks them does, so they are compared as they are stored.
    """
    from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("basic "):
        return None

    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None

    try:
        users = DatabaseController().query_systemUser(query=f'name = "{username}"')
    except Exception as ex:
        logger.error("failed looking up %s while enrolling: %s", username, ex, exc_info=True)
        return None

    if not users or users[0].password != password:
        logger.warning("rejected enrollment for %s", username)
        return None
    return users[0]


@page.route("/Marti/api/tls/config")
def tls_config():
    """Describe the naming this server's certificate authority expects."""
    if _authenticated_user() is None:
        return "", 401

    root = Element("ns2:certificateConfig")
    root.set("xmlns", "http://bbn.com/marti/xml/config")
    root.set("xmlns:ns2", "com.bbn.marti.config")

    entries = SubElement(root, "nameEntries")
    SubElement(entries, "nameEntry", {"name": "O", "value": "FTS"})
    SubElement(entries, "nameEntry", {"name": "OU", "value": "Dev"})

    return tostring(root), 200, {"Content-Type": "text/plain; charset=UTF-8"}


@page.route("/Marti/api/tls/signClient", methods=["POST"])
@page.route("/Marti/api/tls/signClient/", methods=["POST"])
@page.route("/Marti/api/tls/signClient/v2", methods=["POST"])
def sign_client():
    """Sign the certificate a client generated for itself."""
    user = _authenticated_user()
    if user is None:
        return "", 401

    client_uid = request.args.get("clientUid") or request.args.get("clientUID")

    # read the body as it arrived: clients label the request in various ways,
    # and anything form-like would otherwise be parsed away before it is read
    raw = request.get_data(cache=False, parse_form_data=False)
    body = _as_pem_request(raw.decode("utf-8", errors="replace"))

    try:
        signed, ca_certificate = certificate_generation.sign_certificate_request(body.encode())
    except Exception as ex:
        logger.error("failed signing a request from %s: %s", user.name, ex, exc_info=True)
        return "", 400

    common_name = certificate_generation.certificate_request_common_name(body.encode())
    logger.info("signed a certificate for %s as %s (client %s)", user.name, common_name, client_uid)

    signed_body = _pem_body(signed)
    ca_body = _pem_body(ca_certificate)

    accept = request.headers.get("Accept", "")
    if accept and "xml" in accept.lower():
        enrollment = Element("enrollment")
        SubElement(enrollment, "signedCert").text = signed_body
        SubElement(enrollment, "ca").text = ca_body
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(enrollment).decode("utf-8"),
            200,
            {"Content-Type": "application/xml"},
        )

    # clients ask for JSON but want it announced as plain text
    return (
        {"signedCert": signed_body, "ca0": ca_body, "ca1": ca_body},
        200,
        {"Content-Type": "text/plain; charset=UTF-8"},
    )


def _as_pem_request(body: str) -> str:
    """A certificate request as PEM, however the client chose to send it.

    Clients send the request as one unbroken run of base64 with no header,
    footer or line breaks, which is not something a PEM reader will accept,
    so it is rebuilt into the shape one expects.
    """
    encoded = "".join(
        line.strip() for line in body.strip().splitlines() if not line.startswith("-----")
    )
    wrapped = "\n".join(encoded[index:index + 64] for index in range(0, len(encoded), 64))
    return (
        "-----BEGIN CERTIFICATE REQUEST-----\n"
        + wrapped
        + "\n-----END CERTIFICATE REQUEST-----\n"
    )


def _pem_body(pem: bytes) -> str:
    """A PEM certificate without its header, footer or line breaks."""
    text = pem.decode("utf-8")
    lines = [line for line in text.splitlines() if line and not line.startswith("-----")]
    return "".join(lines)


@page.route("/Marti/api/tls/profile/enrollment")
def enrollment_profile():
    """The settings a client applies once it has enrolled."""
    if _authenticated_user() is None:
        return "", 401
    return _profile_response()


@page.route("/Marti/api/device/profile/connection")
def connection_profile():
    """The settings a client re-applies when it connects."""
    return _profile_response()


def _profile_response():
    try:
        package = _build_profile_package()
    except Exception as ex:
        logger.error("failed building the enrollment profile: %s", ex, exc_info=True)
        return "", 500

    return Response(
        package,
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=profile.zip"},
    )


def _build_profile_package() -> bytes:
    """A mission package carrying the preferences a client should adopt.

    The channel preferences are the reason this exists: a TAK client keeps
    its channel list hidden for a server until told otherwise, and only ever
    hears otherwise here.
    """
    host = request.host.split(":")[0]

    preferences = Element("preferences")
    preference = SubElement(preferences, "preference", {"version": "1", "name": "com.atakmap.app_preferences"})

    def entry(key, value, kind="class java.lang.String"):
        element = SubElement(preference, "entry", {"key": key, "class": kind})
        element.text = value

    # without these two a client shows an empty channel list however many
    # channels the server offers it
    entry("prefs_enable_channels", "true")
    entry(f"prefs_enable_channels_host-{host}", "true")
    # and this asks the client to pick up profile changes on later connections
    entry("deviceProfileEnableOnConnect", "true", "class java.lang.Boolean")

    manifest = Element("MissionPackageManifest", {"version": "2"})
    configuration = SubElement(manifest, "Configuration")
    SubElement(configuration, "Parameter", {"name": "uid", "value": str(uuid.uuid4())})
    SubElement(configuration, "Parameter", {"name": "name", "value": "Device Profile"})
    SubElement(configuration, "Parameter", {"name": "onReceiveDelete", "value": "true"})
    contents = SubElement(manifest, "Contents")
    SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"{PROFILE_FOLDER}/preference.pref"})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "a", zipfile.ZIP_DEFLATED, False) as package:
        package.writestr("MANIFEST/manifest.xml", tostring(manifest))
        package.writestr(
            f"{PROFILE_FOLDER}/preference.pref",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + tostring(preferences).decode("utf-8"),
        )
    return buffer.getvalue()
