"""The channel selection a TAK client makes for itself.

A client is allowed on the channels its certificate grants it, and chooses
which of those to be active on. The choice belongs to the client, so it is
stored against the client's uid rather than its certificate: two devices
sharing one certificate keep separate selections.
"""
from FreeTAKServer.core.configuration.ChannelConstants import (
    PUBLIC_CHANNEL,
    normalize_channel_input,
    parse_channels,
)

# TAK clients call the channel everyone shares __ANON__, which is this
# server's public channel under another name
ANONYMOUS_CHANNEL = "__ANON__"
from FreeTAKServer.core.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.core.configuration.CreateLoggerController import CreateLoggerController

logger = CreateLoggerController("FTS-Channels", logging_constants=LoggingConstants()).getLogger()


def selected_channel_names(payload) -> list:
    """The channel names marked active in what a TAK client sent.

    Clients send every channel they know about, each flagged active or not,
    in both directions; the name is what identifies the channel here.
    """
    if isinstance(payload, dict):
        groups = payload.get("data", payload.get("groups", []))
    else:
        groups = payload or []
    if isinstance(groups, dict):
        groups = [groups]

    names = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        if not group.get("active", False):
            continue
        name = group.get("name")
        if name == ANONYMOUS_CHANNEL:
            name = PUBLIC_CHANNEL
        if name and name not in names:
            names.append(name)
    return names


def store_selection(client_uid, payload) -> list:
    """Record a client's channel selection and report what was stored."""
    from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

    names = selected_channel_names(payload)
    try:
        DatabaseController().update_user(
            column_value={"active_channels": normalize_channel_input(names)},
            query=f'uid = "{client_uid}"',
        )
    except Exception as ex:
        # a client that cannot store its choice still has to keep working, on
        # everything its certificate allows
        logger.error("failed storing channel selection for %s: %s", client_uid, ex, exc_info=True)
        return []

    logger.debug("client %s is now active on %s", client_uid, names or "all of its channels")
    return names


def selection_for_client(client_uid=None, address=None):
    """The stored selection for a client, by uid or by the address it calls from.

    Clients ask for their channel list without identifying themselves, so the
    address of the request is the only thing left to match them on. Returns
    None when no client is matched or none has chosen, meaning every channel
    the client is allowed on is active.
    """
    from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

    if not client_uid and not address:
        return None, None

    query = f'uid = "{client_uid}"' if client_uid else f'IP = "{address}"'
    try:
        users = DatabaseController().query_user(query=query)
    except Exception as ex:
        logger.debug("failed resolving client for %s: %s", query, ex)
        return None, None

    if not users:
        return None, None

    user = users[0]
    selection = getattr(user, "active_channels", None)
    return getattr(user, "CN", None), parse_channels(selection) if selection else None


def allowed_channels_for(common_name):
    """The channels a certificate common name is assigned to.

    Returns None when the holder cannot be looked up, meaning nothing is
    known about what they are assigned to rather than that they have nothing.
    """
    from FreeTAKServer.core.configuration.ChannelConstants import system_user_for_common_name
    from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

    if not common_name:
        return None

    try:
        user = system_user_for_common_name(common_name, DatabaseController())
    except Exception as ex:
        logger.debug("failed resolving channels for %s: %s", common_name, ex)
        return None

    if user is None:
        return None
    return parse_channels(getattr(user, "channels", None))
