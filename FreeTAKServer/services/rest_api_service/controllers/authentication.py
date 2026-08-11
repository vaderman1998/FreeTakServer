from flask_httpauth import HTTPTokenAuth
from flask import request
import datetime as dt

auth = HTTPTokenAuth(scheme='Bearer')

# Role granted to a system user whose group is not one of the read-only
# groups below. Historically every system user had unrestricted access and
# the group column was never checked, so unknown/legacy group values (the
# seeded admin's group is "1") must keep full access.
ADMIN_ROLE = "admin"
USER_ROLE = "user"

# Values that grant read-only access: the holder may read state and
# authenticate, but not create/modify/delete users, certificates, federation
# or CoT. Anything else, including unrecognized and legacy values, is an
# administrator, so deployments predating roles are unaffected.
READ_ONLY_ROLES = {"user", "users", "readonly", "read-only", "operator"}

# the role was originally read from the group column
READ_ONLY_GROUPS = READ_ONLY_ROLES


def role_for_value(value) -> str:
    """Map a stored role (or legacy group) onto an authorization role."""
    if value is not None and str(value).strip().lower() in READ_ONLY_ROLES:
        return USER_ROLE
    return ADMIN_ROLE


def role_for_user(user) -> str:
    """Resolve a system user's authorization role.

    The dedicated role column wins; the group column is consulted only for
    users written before roles had their own field.
    """
    role = getattr(user, "role", None)
    if role is None or str(role).strip() == "":
        role = getattr(user, "group", None)
    return role_for_value(role)


# retained for callers that pass a bare group value
role_for_group = role_for_value


@auth.verify_token
def verify_token(token):
    from .persistency import dbController
    if token:
        output = dbController.query_APIUser(query=f'token = "{token}"')
        if output:
            return output[0].Username
        else:
            output = dbController.query_systemUser(query=f'token = "{token}"')
            if output:
                output = output[0]
                r = request
                dbController.create_APICall(user_id=output.uid, timestamp=dt.datetime.now(), content=request.data,
                                            endpoint=request.base_url)
                return output.name


@auth.get_user_roles
def get_user_roles(user):
    """Resolve the roles of the authenticated principal.

    API users (the /APIUser table, only creatable from AllowCLIIPs) keep
    unrestricted access. System users are restricted by their group.
    """
    from .persistency import dbController

    if dbController.query_APIUser(query=f'Username = "{user}"'):
        return [ADMIN_ROLE, USER_ROLE]

    output = dbController.query_systemUser(query=f'name = "{user}"')
    if output:
        role = role_for_user(output[0])
        return [ADMIN_ROLE, USER_ROLE] if role == ADMIN_ROLE else [USER_ROLE]
    return [USER_ROLE]
