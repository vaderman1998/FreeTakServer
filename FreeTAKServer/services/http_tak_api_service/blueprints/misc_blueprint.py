import json
from flask import Blueprint, request, make_response
from FreeTAKServer.core.configuration.MainConfig import MainConfig

config = MainConfig.instance()
page = Blueprint('misc', __name__)

@page.route("/Marti/api/groups/groupCacheEnabled")
def group_cache():
    # advertises that this server serves channels: clients skip loading the
    # channel list entirely when this is false
    return {
        "version": "3",
        "type": "java.lang.Boolean",
        "data": True,
        "nodeId": config.nodeID
    }

@page.route('/Marti/api/clientEndPoints', methods=["GET"])
def clientEndPoint():
    return {
        "version": "3",
        "type": "com.bbn.marti.remote.ClientEndpoint",
        "data": [
            {
                "callsign": "DOWN",
                "uid": "ANDROID-199eeda473669973",
                "username": "ghost",
                "lastEventTime": "2023-06-16T15:20:55.871Z",
                "lastStatus": "Connected"
            }
        ],
        "nodeId": config.nodeID
    }


@page.route('/Marti/api/groups/active', methods=['PUT'])
def put_groups_active():
    """Record which of its channels a client wants to be active on.

    The certificate a client connects with decides which channels it may use
    at all; this narrows that set to the ones the operator selected in their
    TAK client. Storing it against the client's uid keeps one device's choice
    from changing another's, even when both use the same certificate.
    """
    from FreeTAKServer.core.persistence.channel_selection import store_selection

    client_uid = request.args.get("clientUid")
    if not client_uid:
        return {"version": "3", "type": "java.lang.Boolean", "data": False,
                "nodeId": config.nodeID}, 400

    store_selection(client_uid, request.get_json(silent=True))
    return {
        "version": "3",
        "type": "java.lang.Boolean",
        "data": True,
        "nodeId": config.nodeID
    }


@page.route('/Marti/api/groups/activebits', methods=['GET', 'PUT'])
def groups_activebits():
    """Report or accept the active channel bit positions for a client."""
    return {
        "version": "3",
        "type": "java.lang.Boolean",
        "data": True,
        "nodeId": config.nodeID
    }


@page.route('/Marti/api/groups/activeForce')
def groups_active_force():
    """Report the forced channel selection for a user; none is forced here."""
    return {
        "name": "",
        "distinguishedName": "",
        "direction": "",
        "created": "",
        "bitpos": 0,
        "active": True,
        "description": "",
        "type": "SYSTEM",
    }


@page.route('/Marti/api/groups/user')
def groups_for_user():
    return {
        "version": "3",
        "type": "com.bbn.marti.remote.groups.Group",
        "data": {},
        "messages": [""],
        "nodeId": config.nodeID
    }


@page.route('/Marti/api/groupprefix')
def groups_prefix():
    return {
        "version": "3",
        "type": "java.lang.String",
        "data": "",
        "nodeId": config.nodeID
    }


@page.route('/Marti/api/subscriptions/all')
def subscriptions_all():
    return {
        "version": "3",
        "type": "SubscriptionInfo",
        "data": [],
        "messages": [],
        "nodeId": config.nodeID
    }
