#!/usr/bin/env bash
# Verify role-based access control: admin keeps full access, limited user is
# blocked from admin actions at both the API and UI layers.
S=$(mktemp -d)
source /etc/fts/secrets.txt
LIMITED_USER=roletest-limited
LIMITED_TOKEN=roletest-limited-token
LIMITED_PASS=roletest-limited-pass
VENV=${VENV:-/root/FreeTakServer/.venv}

# provision the read-only fixture user so the suite is self-contained
"$VENV/bin/python" - "$LIMITED_USER" "$LIMITED_TOKEN" "$LIMITED_PASS" <<'PYFIX'
import sys, uuid
from FreeTAKServer.core.persistence.DatabaseController import DatabaseController
name, token, password = sys.argv[1:4]
db = DatabaseController()
if not db.query_systemUser(query=f'name = "{name}"'):
    db.create_systemUser(name=name, group="user", token=token, password=password,
                         uid=str(uuid.uuid4()), device_type="mobile")
PYFIX
PASS=0
FAIL=0

check() { # description expected actual
  if [[ "$2" == "$3" ]]; then echo "  PASS: $1 (got $3)"; PASS=$((PASS+1));
  else echo "  FAIL: $1 (expected $2, got $3)"; FAIL=$((FAIL+1)); fi
}

code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

echo "== API: admin token =="
check "admin can list system users" 200 \
  "$(code -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:19023/ManageSystemUser/getAll)"
check "admin can read video streams" 200 \
  "$(code -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:19023/ManageVideoStream/getVideoStream)"

echo "== API: limited token (group=user) =="
check "limited BLOCKED from listing system users" 403 \
  "$(code -H "Authorization: Bearer $LIMITED_TOKEN" http://127.0.0.1:19023/ManageSystemUser/getAll)"
check "limited BLOCKED from creating a user" 403 \
  "$(code -X POST -H "Authorization: Bearer $LIMITED_TOKEN" -H 'Content-Type: application/json' \
     -d '{"systemUsers":[{"Name":"eviluser","Group":"admin","Token":"x","Password":"y","DeviceType":"mobile"}]}' \
     http://127.0.0.1:19023/ManageSystemUser/postSystemUser)"
check "limited BLOCKED from deleting a user" 403 \
  "$(code -X DELETE -H "Authorization: Bearer $LIMITED_TOKEN" http://127.0.0.1:19023/ManageSystemUser/deleteSystemUser?Name=admin)"
check "limited BLOCKED from broadcasting chat" 403 \
  "$(code -X POST -H "Authorization: Bearer $LIMITED_TOKEN" -H 'Content-Type: application/json' \
     -d '{"message":"pwned"}' http://127.0.0.1:19023/ManageChat/postChatToAll)"
check "limited BLOCKED from federation table" 403 \
  "$(code -H "Authorization: Bearer $LIMITED_TOKEN" http://127.0.0.1:19023/FederationTable)"
check "limited BLOCKED from video stream mgmt" 403 \
  "$(code -X DELETE -H "Authorization: Bearer $LIMITED_TOKEN" http://127.0.0.1:19023/ManageVideoStream/deleteVideoStream)"
check "no token still rejected" 401 \
  "$(code http://127.0.0.1:19023/ManageSystemUser/getAll)"
check "postSystemUser blueprint requires auth (was unauthenticated)" 401 \
  "$(code -X POST -H 'Content-Type: application/json' -d '{"systemUsers":[]}' \
     http://127.0.0.1:19023/ManageSystemUser/postSystemUser)"
check "GenerateQR requires auth (was unauthenticated)" 401 \
  "$(code 'http://127.0.0.1:19023/GenerateQR?datapackage_hash=abc')"

echo "== UI: admin login =="
rm -f $S/c_admin
curl -s -c $S/c_admin http://127.0.0.1:5000/login -o $S/l_admin.html
CSRF=$(grep -oP 'name="csrf_token"[^>]*value="\K[^"]+' $S/l_admin.html | head -1)
curl -s -b $S/c_admin -c $S/c_admin -X POST http://127.0.0.1:5000/login \
  -d "username=admin&password=$ADMIN_PASSWORD&csrf_token=$CSRF&login=" -o /dev/null
check "admin reaches dashboard" 200 "$(code -b $S/c_admin http://127.0.0.1:5000/index)"
check "admin reaches /users" 200 "$(code -b $S/c_admin http://127.0.0.1:5000/users)"
check "admin reaches /configure" 200 "$(code -b $S/c_admin http://127.0.0.1:5000/configure)"
check "admin reaches /page-user" 200 "$(code -b $S/c_admin http://127.0.0.1:5000/page-user)"
curl -s -b $S/c_admin http://127.0.0.1:5000/index -o $S/dash_admin.html
if grep -q 'href="/users"' $S/dash_admin.html; then echo "  PASS: admin sidebar shows User link"; PASS=$((PASS+1));
else echo "  FAIL: admin sidebar missing User link"; FAIL=$((FAIL+1)); fi

echo "== UI: limited login (group=user) =="
rm -f $S/c_ltd
curl -s -c $S/c_ltd http://127.0.0.1:5000/login -o $S/l_ltd.html
CSRF2=$(grep -oP 'name="csrf_token"[^>]*value="\K[^"]+' $S/l_ltd.html | head -1)
curl -s -b $S/c_ltd -c $S/c_ltd -X POST http://127.0.0.1:5000/login \
  -d "username=$LIMITED_USER&password=$LIMITED_PASS&csrf_token=$CSRF2&login=" -o /dev/null
check "limited reaches dashboard" 200 "$(code -b $S/c_ltd http://127.0.0.1:5000/index)"
check "limited BLOCKED from /users" 403 "$(code -b $S/c_ltd http://127.0.0.1:5000/users)"
check "limited BLOCKED from /configure" 403 "$(code -b $S/c_ltd http://127.0.0.1:5000/configure)"
check "limited BLOCKED from /page-user (leaks API key)" 403 "$(code -b $S/c_ltd http://127.0.0.1:5000/page-user)"
curl -s -b $S/c_ltd http://127.0.0.1:5000/index -o $S/dash_ltd.html
if grep -q 'href="/users"' $S/dash_ltd.html; then echo "  FAIL: limited sidebar still shows User link"; FAIL=$((FAIL+1));
else echo "  PASS: limited sidebar hides User link"; PASS=$((PASS+1)); fi
if grep -qi "$API_TOKEN" $S/dash_ltd.html; then echo "  FAIL: API token leaked to limited user"; FAIL=$((FAIL+1));
else echo "  PASS: no API token in limited user's dashboard"; PASS=$((PASS+1)); fi

echo
echo "RESULT: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
