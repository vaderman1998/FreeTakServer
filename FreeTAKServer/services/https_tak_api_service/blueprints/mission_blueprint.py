import json
from uuid import uuid4
from flask import Blueprint, request
from FreeTAKServer.core.configuration.MainConfig import MainConfig
from FreeTAKServer.services.https_tak_api_service.controllers.https_tak_api_communication_controller import HTTPSTakApiCommunicationController

from FreeTAKServer.core.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.core.configuration.CreateLoggerController import CreateLoggerController
logger = CreateLoggerController("FTS-Mission", logging_constants=LoggingConstants()).getLogger()

def _as_response(value):
    """Coerce a component's return value into something Flask can send.

    The mission components return domain objects as well as strings and
    dicts; returning an object Flask cannot serialize raises after the view
    has already succeeded, which surfaced as a 500 on requests that had in
    fact done their work.
    """
    import json as _json

    if isinstance(value, (str, bytes, dict, list)):
        return value
    for attribute in ("to_json", "toJson"):
        if hasattr(value, attribute):
            try:
                return getattr(value, attribute)()
            except Exception:
                pass
    if hasattr(value, "__dict__"):
        try:
            return _json.dumps(
                {k: v for k, v in vars(value).items() if not k.startswith("_")},
                default=str,
            )
        except Exception:
            pass
    return _json.dumps(value, default=str)


page = Blueprint("mission", __name__)
config = MainConfig.instance()

@page.route('/Marti/api/missions', methods=['GET'])
def get_missions():
    out_data =  HTTPSTakApiCommunicationController().make_request("GetMissions", "mission", {}, None, True).get_value("missions"), 200
    print(out_data)
    return out_data

@page.route('/Marti/api/missions/invitations')
def get_invitations():
    client_uid = request.args.get("clientUid", None)
    if client_uid is None:
        return '', 400
    out_data = HTTPSTakApiCommunicationController().make_request("GetInvitations", "mission", {"client_uid": client_uid}, None, synchronous=True).get_value("mission_changes") # type: ignore
    return out_data, 200

@page.route('/Marti/api/groups/all')
def get_groups():
    """Report the channels this server defines to TAK clients.

    Clients list these as channels; membership is still enforced by the CoT
    services from the certificate a client connects with, so a channel
    appearing here does not grant access to its traffic.
    """
    from FreeTAKServer.core.persistence.DatabaseController import DatabaseController

    groups = []
    try:
        channels = DatabaseController().query_channel()
    except Exception:
        channels = []

    # every channel is reported in both directions, as TAK clients expect
    for index, channel in enumerate(channels):
        for direction in ("IN", "OUT"):
            groups.append({
                "name": channel.name,
                "direction": direction,
                "created": "2023-02-22",
                "type": "SYSTEM",
                "bitpos": index + 3,
                "active": True,
                "description": channel.description or "",
            })

    # the anonymous group is what clients fall back to, and is the only group
    # when no channels have been defined
    for direction in ("IN", "OUT"):
        groups.append({
            "name": "__ANON__",
            "direction": direction,
            "created": "2023-02-22",
            "type": "SYSTEM",
            "bitpos": 2,
            "active": True,
            "description": "",
        })

    return {
        "version": "3",
        "type": "com.bbn.marti.remote.groups.Group",
        "data": groups,
        "nodeId": config.nodeID
    }
    
@page.route('/Marti/api/missions/<mission_id>', methods=['PUT'])
def put_mission(mission_id):
    from flask import request
    try:
        subscription = HTTPSTakApiCommunicationController().make_request("PutMission", "mission", {"mission_id": mission_id, "mission_data": request.data, "mission_data_args": request.args, "creatorUid": request.args.get("creatorUid")}, None, True).get_value("mission_subscription") # type: ignore
        HTTPSTakApiCommunicationController().make_request("MissionCreatedNotification", "mission", {"mission_id": mission_id}, None, synchronous=False)
    except Exception as ex:
        logger.error("failed creating mission %s: %s", mission_id, ex, exc_info=True)
        return {"message": "An error occurred creating the mission."}, 500

    if subscription is None:
        # the mission is persisted even when no subscription comes back, so
        # returning an empty body here would fail the client for no reason
        logger.error("mission %s created but no subscription was returned", mission_id)
        return {"version": "3", "type": "Mission", "data": [], "nodeId": config.nodeID}, 201
    return _as_response(subscription), 200

@page.route('/Marti/api/missions/<mission_id>', methods=['GET'])
def get_mission(mission_id):
    from flask import request
    try:
        mission = HTTPSTakApiCommunicationController().make_request("GetMission", "mission", {"mission_id": mission_id}, None, True).get_value("mission")
    except Exception as ex:
        logger.error("failed retrieving mission %s: %s", mission_id, ex, exc_info=True)
        return {"message": "An error occurred retrieving the mission."}, 500

    if mission is None:
        return {"message": f"no mission named {mission_id}"}, 404
    return _as_response(mission), 200

@page.route('/Marti/api/missions/<mission_id>/cot', methods=['GET'])
def get_mission_cots(mission_id):
    """get all cots for a mission"""
    return HTTPSTakApiCommunicationController().make_request("GetMissionCots", "mission", {"mission_id": mission_id}, None, True).get_value("cots"), 200

@page.route('/Marti/api/missions/<mission_id>/contents', methods=['PUT'])
def add_mission_contents(mission_id: str):
    """add contents to a mission

    Args:
        mission_id (str): the id of the mission to add contents to
    """
    request_json = request.get_json() # type: ignore
    return_data = HTTPSTakApiCommunicationController().make_request("AddMissionContents", "mission", {"mission_id": mission_id, "hashes": request_json.get("hashes", []), "uids": request_json.get("uids", [])}, None, True).get_value("mission")
    for hash in request_json.get("hashes", []):
        HTTPSTakApiCommunicationController().make_request("MissionContentCreatedNotification", "mission", {"content_id": hash}, None, synchronous=False)
        
    return return_data, 200

@page.route('/Marti/api/missions/logs/entries', methods=['POST'])
def add_log_entry():
    request_json = request.get_json() # type: ignore
    return_data =  HTTPSTakApiCommunicationController().make_request("AddMissionLog", "mission", {"mission_log_data": request_json}, None, True).get_value("log")
    HTTPSTakApiCommunicationController().make_request("MissionLogCreatedNotification", "mission", {"log_id": json.loads(return_data)["data"][0]["id"]}, None, synchronous=False)
    return return_data, 200

@page.route('/Marti/api/missions/logs/entries', methods=['PUT'])
def update_log_entry():
    request_json = request.get_json() # type: ignore
    return HTTPSTakApiCommunicationController().make_request("UpdateMissionLog", "mission", {"mission_log_data": request_json}, None, True).get_value("log"), 200

@page.route('/Marti/api/missions/logs/entries/<id>', methods=['DELETE'])
def delete_log_entry(id):
    HTTPSTakApiCommunicationController().make_request("DeleteMissionLog", "mission", {"log_id": id}, None, True)
    return "", 200

@page.route('/Marti/api/missions/logs/entries/<id>', methods=['GET'])
def get_log_entry():
    return HTTPSTakApiCommunicationController().make_request("GetMissionLog", "mission", {"log_id": id}, None, True).get_value("log"), 200

@page.route('/Marti/api/missions/<missionID>/log', methods=['GET'])
def get_mission_logs(missionID):
    return HTTPSTakApiCommunicationController().make_request("GetMissionLogs", "mission", {"mission_id": missionID, "seconds_ago": request.args.get("secago"), "start": request.args.get("start"), "end": request.args.get("end")}, None, True).get_value("logs"), 200

@page.route('/Marti/api/missions/all/logs', methods=['GET'])
def get_all_logs():
    return HTTPSTakApiCommunicationController().make_request("GetAllLogs", "mission", {}, None, True).get_value("logs"), 200

@page.route('/Marti/api/missions/<child_mission_id>/parent/<parent_mission_id>', methods=['PUT'])
def add_child_to_parent(child_mission_id, parent_mission_id):
    HTTPSTakApiCommunicationController().make_request("AddChildToParent", "mission", {"child_mission_id": child_mission_id, "parent_mission_id": parent_mission_id}, None, True)
    return '', 200

@page.route('/Marti/api/missions/<child_mission_id>/parent', methods=['DELETE'])
def delete_child(child_mission_id):
    return HTTPSTakApiCommunicationController().make_request("DeleteParent", "mission", {"child_mission_id": child_mission_id}, None, True).get_value("mission"), 200

@page.route('/Marti/api/missions/<parent_mission_id>/children', methods=['GET'])
def get_children(parent_mission_id):
    return HTTPSTakApiCommunicationController().make_request("GetChildren", "mission", {"parent_mission_id": parent_mission_id}, None, True).get_value("children"), 200

@page.route('/Marti/api/missions/<child_mission_id>/parent', methods=['GET'])
def get_parent(child_mission_id):
    return HTTPSTakApiCommunicationController().make_request("GetParent", "mission", {"child_mission_id": child_mission_id}, None, True).get_value("parent"), 200

@page.route('/Marti/api/missions/all/subscriptions', methods=['GET'])
def get_all_subscriptions():
    return HTTPSTakApiCommunicationController().make_request("GetAllSubscriptions", "mission", {}, None, True).get_value("mission_subscriptions"), 200

@page.route('/Marti/api/missions/<mission_id>/subscriptions', methods=['GET'])
def get_mission_subscriptions(mission_id):
    return HTTPSTakApiCommunicationController().make_request("GetMissionSubscriptions", "mission", {"mission_id": mission_id}, None, True).get_value("mission_subscriptions"), 200

@page.route('/Marti/api/missions/<mission_id>/subscription', methods=['PUT'])
def add_mission_subscription(mission_id):
    try:
        uid = request.args.get("uid") # type: ignore
        topic = request.args.get("topic") # type: ignore
        password = request.args.get("password") # type: ignore
        secago = request.args.get("secago") # type: ignore
        start = request.args.get("start") # type: ignore
        end = request.args.get("end") # type: ignore
        mission_subscription_data = HTTPSTakApiCommunicationController().make_request("AddMissionSubscription", "mission", {"mission_id": mission_id, 
                                                                                                    "client": uid, 
                                                                                                    "topic": topic, 
                                                                                                    "password": password, 
                                                                                                    "secago": secago,
                                                                                                    "start": start,
                                                                                                    "end": end},
                                                                None, True).get_value("mission_subscription")
        if mission_subscription_data is not None:
            return mission_subscription_data, 201
        else:
            return '', 404
    except Exception as e:
        print(e)
        return '', 500
@page.route('/Marti/api/missions/<mission_id>/subscription', methods=['DELETE'])
def delete_mission_subscription(mission_id):
    uid = request.args.get("uid") # type: ignore
    topic = request.args.get("topic") # type: ignore
    disconnectOnly = request.args.get("disconnectOnly") # type: ignore
    HTTPSTakApiCommunicationController().make_request("DeleteMissionSubscription", "mission", {"mission_id": mission_id, "client": uid, "topic": topic, "disconnect_only": disconnectOnly}, None, True)
    return '', 200

@page.route('/Marti/api/missions/<mission_id>/subscription', methods=['GET'])
def get_mission_subscription(mission_id):
    uid = request.args.get("uid") # type: ignore
    return HTTPSTakApiCommunicationController().make_request("GetMissionSubscription", "mission", {"mission_id": mission_id, "client": uid}, None, True).get_value("mission_subscription"), 200

@page.route('/Marti/api/missions/<mission_id>/subscriptions/roles', methods=['GET'])
def get_all_mission_subscriptions(mission_id):
    """get all the subscriptions from a mission

    Args:
        mission_id (_type_): _description_
    """
    print("request made to get all mission subscriptions")
    out_data = HTTPSTakApiCommunicationController().make_request("GetMissionSubscriptions", "mission", {"mission_id": mission_id}, None, True).get_value("mission_subscriptions"), 200
    print(out_data)
    return out_data

@page.route('/Marti/api/missions/<mission_id>/externaldata', methods=['POST'])
def create_external_mission_data(mission_id):
    """create external mission data

    Args:
        mission_id (_type_): _description_
    """
    request_json = request.get_json() # type: ignore
    out_data = HTTPSTakApiCommunicationController().make_request("CreateExternalMissionData", "mission", {"mission_id": mission_id, "mission_external_data": request_json}, None, True).get_value("external_data"), 200 # type: ignore
    return out_data

@page.route('/Marti/api/missions/<mission_id>/changes', methods=['GET'])
def get_mission_changes(mission_id):
    """get mission changes

    Args:
        mission_id (_type_): _description_
    """
    out_data = HTTPSTakApiCommunicationController().make_request("GetMissionChanges", "mission", {"mission_id": mission_id}, None, True).get_value("mission_changes"), 200
    return out_data

@page.route('/Marti/api/missions/<mission_id>/contents/missionpackage', methods=["PUT"])
def add_mission_content_direct(mission_id):
    filename = request.args.get("filename")
    creatorUid = request.args.get("creatorUid")
    tool = request.args.get("tool", "public")
    if not request.data:
        data = request.files.getlist('assetfile')[0].stream.read()
    else:
        data = request.data

    if request.args.get("hash", None) == None:
        id = str(uuid4())
    else:
        id = request.args.get("hash")

    metadata = HTTPSTakApiCommunicationController().make_request("SaveEnterpriseSyncData", "enterpriseSync", {"objectuid": id, "tool": tool, "objectdata": data, "objkeywords": [filename, creatorUid, "missionpackage"], "objstarttime": "", "synctype": "content", "mime_type": request.headers["Content-Type"]}, None, True).get_value("objectmetadata") # type: ignore

    HTTPSTakApiCommunicationController().make_request("AddMissionContents", "mission", {"mission_id": mission_id, "hashes": [metadata.hash], "uids": []}, None, True).get_value("mission"),200

    return {
        "version": "3",
        "type": "MissionChange",
        "data": [],
        "nodeId": config.nodeID
    }

@page.route('/Marti/api/missions/<mission_id>/invite/<type>/<invitee>', methods=["PUT"])
def put_mission_invitation(mission_id, type, invitee):
    """post the invitation for a mission"""
    author = request.args.get("creatorUid", "unknown")
    invitedContacts = invitee
    role = request.args.get("role", None)
    try:
        mission = HTTPSTakApiCommunicationController().make_request("GetMission", "mission", {"mission_id": mission_id}, None, True).get_value("mission")
        if mission == None:
            return '{"message": "mission not found"}', 404
        default_mission_role = json.loads(mission)["data"][0]["defaultRole"]["type"]
        if role is None or role == default_mission_role:
            HTTPSTakApiCommunicationController().make_request("SendInvitation", "mission", {"author_uid": author, "mission_id": mission_id, "client_uid": invitedContacts, "role": role}, None, False)
        else:
            return '{"message": "invalid role"}', 405
        return '', 200
    except Exception as e:
        print(e)
        return {"message": str(e)}, 500
    
@page.route('/Marti/api/missions/<mission_id>/invite', methods=["POST"])
def post_mission_invitation(mission_id):
    """post the invitation for a mission"""
    author = request.args.get("creatorUid", "unknown")
    invitedContacts = request.args.get("contacts", None)
    if request.data != b'':
        invitedContacts = json.loads(request.data)[0]["invitee"]
        role = json.loads(request.data)[0]["role"]["type"]

    try:
        mission = HTTPSTakApiCommunicationController().make_request("GetMission", "mission", {"mission_id": mission_id}, None, True).get_value("mission")
        if mission == None:
            return '{"message": "mission not found"}', 404
        role = json.loads(mission)["data"][0]["defaultRole"]["type"]
        HTTPSTakApiCommunicationController().make_request("SendInvitation", "mission", {"author_uid": author, "mission_id": mission_id, "client_uid": invitedContacts, "role": role}, None, False)
        return '', 200
    except Exception as e:
        print(e)
        return {"message": str(e)}, 500