from typing import TYPE_CHECKING

from flask.json import jsonify

if TYPE_CHECKING:
    from FreeTAKServer.core.enterprise_sync.persistence.sqlalchemy.enterprise_sync_keyword import EnterpriseSyncKeyword
    from FreeTAKServer.core.enterprise_sync.persistence.sqlalchemy.enterprise_sync_data_object import EnterpriseSyncDataObject

import json
from flask import Blueprint, request
from pathlib import PurePath, Path
import hashlib
from zipfile import ZipFile
from defusedxml import ElementTree as etree
import uuid
from lxml.etree import SubElement, Element  # pylint: disable=no-name-in-module

from ..controllers.authentication import auth, ADMIN_ROLE

from FreeTAKServer.core.configuration.MainConfig import MainConfig
from FreeTAKServer.core.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.core.configuration.CreateLoggerController import CreateLoggerController
from FreeTAKServer.services.rest_api_service.controllers.rest_api_communication_controller import RestAPICommunicationController

loggingConstants = LoggingConstants()
logger = CreateLoggerController("FTS-RestAPI_Service", logging_constants=loggingConstants).getLogger()

config = MainConfig.instance()
page = Blueprint('mission', __name__)

@page.route("/MissionTable", methods=['GET'])
@auth.login_required()
def get_mission_table():
    try:
        return RestAPICommunicationController().make_request("GetMissions", "mission", {}, None, True).get_value("missions"), 200
    except Exception as e:
        logger.error("failed listing missions: %s", e, exc_info=True)
        return {"message":"An error occurred accessing mission details."}, 500

@page.route("/MissionTable", methods=['POST'])
@auth.login_required(role=ADMIN_ROLE)
def post_mission_table():
    """create a mission from the UI"""
    request_json = request.get_json(silent=True) or {}
    name = str(request_json.get("name", "")).strip()
    if not name:
        return {"message": "a mission name is required"}, 400

    try:
        existing = RestAPICommunicationController().make_request("GetMission", "mission", {"mission_id": name}, None, True).get_value("mission")
    except Exception as e:
        logger.error("failed checking for mission %s: %s", name, e, exc_info=True)
        return {"message": "An error occurred creating the mission."}, 500

    if existing is not None:
        return {"message": f"a mission named {name} already exists"}, 409

    # the component reads the mission's fields from the arguments when no
    # body is supplied, which is the same path ATAK uses
    mission_args = {
        "description": str(request_json.get("description", "")),
        "tool": str(request_json.get("tool", "public")),
        "creatorUid": str(request_json.get("creatorUid", auth.current_user())),
    }
    try:
        RestAPICommunicationController().make_request("PutMission", "mission", {
            "mission_id": name,
            "mission_data": b'',
            "mission_data_args": mission_args,
            "creatorUid": mission_args["creatorUid"],
        }, None, True)
        RestAPICommunicationController().make_request("MissionCreatedNotification", "mission", {"mission_id": name}, None, synchronous=False)
    except Exception as e:
        logger.error("failed creating mission %s: %s", name, e, exc_info=True)
        return {"message": "An error occurred creating the mission."}, 500

    return {"message": f"mission {name} created"}, 201

@page.route("/MissionTable", methods=['DELETE'])
@auth.login_required(role=ADMIN_ROLE)
def delete_mission_table():
    """delete one or more missions from the UI"""
    request_json = request.get_json(silent=True) or {}
    names = request_json.get("names")
    if names is None:
        name = request_json.get("name") or request.args.get("name")
        names = [name] if name else []
    if isinstance(names, str):
        names = [names]
    names = [str(name).strip() for name in names if str(name).strip()]
    if not names:
        return {"message": "a mission name is required"}, 400

    deleted, missing = [], []
    for name in names:
        try:
            was_deleted = RestAPICommunicationController().make_request("DeleteMission", "mission", {"mission_id": name}, None, True).get_value("mission_deleted")
        except Exception as e:
            logger.error("failed deleting mission %s: %s", name, e, exc_info=True)
            return {"message": "An error occurred deleting the mission."}, 500
        (deleted if was_deleted else missing).append(name)

    if not deleted:
        return {"message": f"no mission named {', '.join(missing)}"}, 404
    return {"message": f"deleted {', '.join(deleted)}", "deleted": deleted, "missing": missing}, 200
