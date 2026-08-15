# FreeTAKServer — working notes for this fork

A fork of FreeTAKServer (upstream stale since Oct 2024) being modernised and run
in production on a Raspberry Pi. Read this before changing anything: most of it
is knowledge that cost a lot of debugging to learn.

## Where things are

| | |
|---|---|
| Server | `/root/FreeTakServer`, branch `fix/broken-out-of-box-startup` |
| UI | `/root/FTS-UI-fork` (separate repo, branch `feature/role-based-access`) |
| Installer | `/root/FTH-install-fork`, branch `fts-fixed-branch` |
| Data | `/opt/fts` — databases, certificates, config |
| Secrets | `/etc/fts/secrets.txt`, `/etc/fts/fts.env`, `/etc/fts/fts-ui.env` (all 600) |
| ATAK 5.6 SDK | `/root/ATAK-CIV-5.6.0.21-SDK` — the reference for client behaviour |

Ports: 8087 TCP CoT, 8089 SSL CoT, 8080 HTTP API, 8443 HTTPS API,
8446 certificate enrolment, 19023 REST API, 5000 UI.

## Running it

```bash
systemctl restart fts          # ~25s to come up; always sleep before testing
systemctl restart fts-ui
journalctl -u fts -f
curl -s http://127.0.0.1:8080/Marti/api/version
```

The server **runs from this git checkout** (`freetakserver.pth` → editable
install), so a code change needs only a restart. The **UI does not**: it runs
from `site-packages/FreeTAKServer-UI`, so a UI change needs

```bash
cd /root/FTS-UI-fork && /root/FreeTakServer/.venv/bin/pip install --no-deps --force-reinstall .
systemctl restart fts-ui
```

## Landmines

**Duplicated files.** Several files exist in near-identical copies and a fix
applied to one silently does nothing:

- `services/http_tak_api_service/blueprints/*` and `services/https_tak_api_service/blueprints/*`
- `services/tcp_cot_service/*` and `services/ssl_cot_service/*`
- `controllers/mission_director.py` (base class) vs `controllers/directors/mission_director.py` (the real one)
- `core/services/RestAPI.py` is dead code; the live one is `services/rest_api_service/`

Always `git show --stat <commit>` after editing to confirm which copy changed.
An entire session was lost to patching only the https copy while testing 8080.

**Processes don't share memory.** The REST API, the CoT services and the HTTP
APIs are separate processes. Anything one changes at runtime is invisible to the
others — that is why the connection message lives in a file and channel state
lives in the database.

**SQLAlchemy sessions hold a snapshot.** A long-lived session keeps reading the
state it first saw, so a row another process just wrote is invisible. Call
`session.rollback()` then `session.expire_all()` before reading — see
`_fresh()` in `core/persistence/channel_selection.py`. In SQLAlchemy 2.0 an
`UPDATE` also needs an explicit `connection.commit()`; DDL autocommits and DML
does not, which silently reverted a migration once.

**Exceptions are swallowed everywhere.** Upstream catches broadly and returns a
generic message. When something fails for no visible reason, the handler is
probably discarding the error — add `logger.error(..., exc_info=True)` first.

## Certificates — read before touching

- **Server certificates need a SAN.** Clients stopped matching on common name
  years ago. A client with its own certificate never checks, so this stayed
  hidden until enrolment, which has nothing else to check. Reissue with
  `tools/reissue_server_certificate.py <address>`.
- **A truststore must be readable by Java.** Its certificates need a
  `friendlyName`, because that is the alias the client enumerates; an unnamed
  certificate is invisible and the client trusts nothing. Verify with
  `openssl pkcs12 -in store.p12 -nokeys -passin pass:atakatak -legacy`, which
  must print `friendlyName:`.
- **Use legacy encryption.** `_p12_encryption()` in `certificate_generation.py`.
  Clients cannot read a modern AES store.
- **Truststore password is `atakatak`** — what a client falls back to when it
  has nothing recorded for the server.
- **Packages ship the authority, never the server's certificate.** Pinning the
  server's certificate breaks every client when it is reissued, and shipping
  `server.p12` hands out the server's private key. See `build_ca_truststore()`.
- Certificates issued through the API are named `username + uid`, not the
  username — `system_user_for_common_name()` handles both forms.

## Channels

Membership comes from the certificate common name → `SystemUser.channels`.
A client picks which of those to listen on, stored per device in
`User.active_channels`; the selection can only narrow, never widen.

`groups/all` carries no client identity, so the caller is matched on the address
it calls from against `User.IP`. This is the weak point: it needs each device on
its own address, and a stale row for a previous user will answer for it (hence
`forget_other_clients_at()`). Client-certificate identity on 8443 would fix it
properly, but the HTTPS service does not expose the peer certificate.

`public` is this server's shared channel; clients call it `__ANON__`. A user
with no channels is public-only.

## Client behaviour

Read the SDK rather than guessing — the public CIV source is 4.6 and the
deployed client is 5.6, and they differ. There is no Java source in the SDK, but
the class constant pools are readable:

```python
import re, zipfile
z = zipfile.ZipFile("/root/ATAK-CIV-5.6.0.21-SDK/main.jar")
strings = re.findall(rb'[\x20-\x7e]{5,}', z.read("gov/tak/platform/engine/net/CertificateManagerBase.class"))
```

Better still, compare against a known-good artefact. Every enrolment fault was
found by diffing against a working package from a real TAK server, never by
reasoning from source.

## Tests

```bash
bash tests/security/test_role_access.sh                    # 22 checks
bash tests/security/test_channel_isolation.sh
.venv/bin/python tests/security/test_channel_visibility.py
.venv/bin/python tests/security/test_channel_selection.py
.venv/bin/python tests/security/test_certificate_enrollment.py
.venv/bin/python tests/security/test_server_notifications_reach_channels.py
```

They run against the live server and provision their own fixtures. Run the
relevant ones after any change to certificates, channels or authentication.

## Conventions

- Semantic versioning, bumped in `pyproject.toml` **and**
  `core/configuration/MainConfig.py` (`FTS_VERSION`) together; tag `vX.Y.Z`.
- Push with `GIT_ASKPASS= git push origin <branch>` (the IDE's credential helper
  intercepts otherwise).
- Commit messages describe the behaviour that was wrong and why, not the code.
- Verify against the running server before claiming something works.

## State

FTS 2.13.1, UI 2.5.6. Working: channels with per-user visibility and selection,
Data Sync (missions, items, ownership), certificate enrolment, role-based
access, the UI's user/channel/mission management and connection message.

Open:

- Second Pi (192.168.50.205) still has default credentials and older versions.
- FTS stores system user passwords in plaintext (upstream design). Enrolment
  makes those passwords a joining credential.
- `groups/all` identifies callers by address; see Channels above.
- DigitalPy 0.3.16 upgrade deferred (86 files affected).
- Nothing has been contributed upstream to FreeTAKTeam yet.
