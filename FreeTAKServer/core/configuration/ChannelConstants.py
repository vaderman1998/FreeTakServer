"""Channel (group) membership rules for CoT traffic segregation.

A channel confines CoT traffic to a set of clients: a message is only
delivered to clients that share at least one channel with its sender.

Membership is derived from the certificate a client presents to the SSL CoT
service, which is verified against the server CA, so it cannot be chosen by
the client. Clients on the plain TCP CoT service are not authenticated at
all and are therefore confined to the public channel, where they can only
exchange traffic with other public clients.
"""

# Channel every client belongs to when no other membership is known. Clients
# whose only channel is this one behave exactly as they did before channels
# existed, which keeps existing deployments working untouched.
PUBLIC_CHANNEL = "public"


def parse_channels(raw) -> list:
    """Normalize a stored channel list into a list of channel names.

    Accepts the comma separated string kept on SystemUser rows, an existing
    iterable, or None. Always yields at least the public channel so that a
    client is never isolated by a missing or malformed value.
    """
    if raw is None:
        return [PUBLIC_CHANNEL]

    if isinstance(raw, str):
        names = [name.strip() for name in raw.split(",")]
    else:
        try:
            names = [str(name).strip() for name in raw]
        except TypeError:
            return [PUBLIC_CHANNEL]

    names = [name for name in names if name]
    return names or [PUBLIC_CHANNEL]


def channels_intersect(sender_channels, recipient_channels) -> bool:
    """Whether a message from one channel set may be delivered to another."""
    return bool(set(parse_channels(sender_channels)) & set(parse_channels(recipient_channels)))


def normalize_channel_input(raw) -> str:
    """Normalize channel input from the API into the stored representation.

    Accepts a list of names or a comma separated string and returns the
    canonical comma separated form, or None when the input names no channels
    (meaning public only).
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        names = [name.strip() for name in raw.split(",")]
    else:
        names = [str(name).strip() for name in raw]
    names = [name for name in names if name]
    return ",".join(names) if names else None


# Channel membership is resolved from the database when a client connects.
# Re-reading it for every message would be far too expensive, and never
# re-reading it means changes only apply after a client reconnects, so
# memberships are cached for a short interval and refreshed in the
# background as clients send traffic.
CHANNEL_REFRESH_SECONDS = 15

_membership_cache = {}


def channels_for_common_name(common_name, db_controller, now):
    """Channels granted to a certificate common name, cached briefly."""
    if not common_name:
        return [PUBLIC_CHANNEL]

    cached = _membership_cache.get(common_name)
    if cached is not None and now - cached[0] < CHANNEL_REFRESH_SECONDS:
        return cached[1]

    try:
        users = db_controller.query_systemUser(query=f'name = "{common_name}"')
    except Exception:
        # keep whatever was last known rather than silently isolating a client
        return cached[1] if cached else [PUBLIC_CHANNEL]

    channels = parse_channels(getattr(users[0], "channels", None)) if users else [PUBLIC_CHANNEL]
    _membership_cache[common_name] = (now, channels)
    return channels


def active_channels(allowed, selection) -> list:
    """The channels a client should actually receive traffic on.

    A client chooses which of the channels it is allowed on to listen to.
    The choice can only narrow that set, never widen it, and a client that
    has chosen nothing is active on everything it is allowed.
    """
    allowed = parse_channels(allowed)
    if selection is None:
        return allowed

    chosen = [name for name in parse_channels(selection) if name in allowed]
    # a selection that leaves nothing is treated as no selection, so a client
    # cannot silence itself into looking disconnected
    return chosen or allowed
