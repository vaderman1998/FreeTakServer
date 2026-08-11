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
    """Accept a client's channel selection.

    Which channels a client may actually exchange traffic on is decided by
    the server from the certificate it connects with, so this records the
    client's preference and acknowledges it; clients hide the channel list
    when this endpoint is missing.
    """
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
