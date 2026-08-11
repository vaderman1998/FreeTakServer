from FreeTAKServer.core.configuration.OrchestratorConstants import OrchestratorConstants
from FreeTAKServer.services.ssl_cot_service.controllers.SendDataController import SendDataController
from digitalpy.core.main.object_factory import ObjectFactory
from digitalpy.core.main.controller import Controller

from opentelemetry.trace import Status, StatusCode
from FreeTAKServer.model.RawCoT import RawCoT

from logging import Logger

from FreeTAKServer.services.ssl_cot_service.model.raw_ssl_connection_information import RawSSLConnectionInformation
from FreeTAKServer.core.configuration.LoggingConstants import LoggingConstants
from FreeTAKServer.core.persistence.EventTableController import EventTableController
from FreeTAKServer.model.ClientInformation import ClientInformation
from FreeTAKServer.core.connection.ClientInformationController import (
    ClientInformationController,
)
from FreeTAKServer.model.SSLConnection import SSLConnection
from FreeTAKServer.model.SpecificCoT.Presence import Presence
from FreeTAKServer.core.configuration.ChannelConstants import parse_channels

from ...ssl_cot_service.model.ssl_cot_connection import SSLCoTConnection

APPLICATION_PROTOCOL = "XML"
loggingConstants = LoggingConstants()

class ClientConnectionController(Controller):
    """manage the connection of new clients
    """

    def __init__(self, logger: Logger, client_information_queue, connections, open_sockets):
        self.client_information_controller = ClientInformationController()
        self.logger = logger
        self.client_information_queue = client_information_queue
        self.connections = connections
        self.open_sockets = open_sockets

    def create_client_connection(self, raw_connection_information: RawSSLConnectionInformation, db_controller) -> SSLConnection:
        """Controls the client connection sequence, calling methods which perform the following:
            1. Instantiate the client object
            2. Share the client with core
            3. Add the client to the database
            4. Send the connection message

        :param raw_connection_information: RawSSLConnectionInformation object containing client connection information
        :return: ClientInformation object for the newly connected client, or -1 if there was an error
        """
        from FreeTAKServer.core.persistence.EventTableController import EventTableController        

        # Instantiate the client object
        clientInformation = self.client_information_controller.intstantiateClientInformationModelFromConnection(
            raw_connection_information, None
        )
        self.logger.info(loggingConstants.CLIENTCONNECTED+": %s",clientInformation.modelObject.uid)
        if clientInformation == -1:
            self.logger.info("Client had invalid connection information and has been disconnected")
            return -1

        # Resolve the channels this client's certificate grants before the
        # client is published to the queue, so no traffic can be routed to it
        # while its membership is still unknown
        clientInformation.channels = self.resolve_channels(clientInformation, db_controller)

        # Add client to database
        self.save_client_to_db(clientInformation, db_controller)

        # Add client info to queue
        self.client_information_queue[clientInformation.modelObject.uid] = [clientInformation.socket, clientInformation, raw_connection_information.unwrapped_sock]
        
        # instantiate an object_id with a value of the client uid
        object_id = ObjectFactory.get_new_instance("ObjectId", dynamic_configuration={"id": clientInformation.modelObject.uid, "type": "connection"})
        
        # TODO the instantiation of the connection object and the connection action
        # call should be moved out of the ssl_cot_service main and into the connection
        # controller

        # instantiate a new SSLCoTConnection with an object_id of the client uid
        connection = SSLCoTConnection(object_id)
        connection.model_object = clientInformation.modelObject
        connection.sock = clientInformation.socket
        # carry membership onto the connection so the component broadcast path
        # can enforce it without a database lookup per message
        connection.channels = clientInformation.channels
        self.connections[str(connection.get_oid())] = connection

        return connection, clientInformation

    @staticmethod
    def get_certificate_common_name(sock):
        """Return the common name of the certificate a client presented.

        The SSL CoT service runs with ssl.CERT_REQUIRED against the server CA,
        so a common name obtained here has been verified and identifies the
        client; it is not something the client can assert freely.
        """
        if not hasattr(sock, "getpeercert"):
            return None
        try:
            cert = sock.getpeercert()
        except (ValueError, OSError):
            return None
        if not cert:
            return None
        for rdn in cert.get("subject", ()):
            for key, value in rdn:
                if key == "commonName":
                    return value
        return None

    def resolve_channels(self, clientInformation, db_controller):
        """Resolve the channels a newly connected client may exchange CoT on."""
        common_name = self.get_certificate_common_name(clientInformation.socket)
        # remembered so membership can be refreshed later without another
        # TLS handshake, letting channel changes apply to connected clients
        clientInformation.common_name = common_name
        if not common_name:
            return list(parse_channels(None))
        try:
            users = db_controller.query_systemUser(query=f'name = "{common_name}"')
        except Exception as ex:  # the client must still connect if lookup fails
            self.logger.debug("exception resolving channels for %s: %s", common_name, ex)
            return list(parse_channels(None))
        if not users:
            return list(parse_channels(None))
        return list(parse_channels(getattr(users[0], "channels", None)))

    def save_client_to_db(self, clientInformation, db_controller):
        try:
            cn = self.get_certificate_common_name(clientInformation.socket)
            CoT_row = EventTableController().convert_model_to_row(clientInformation.modelObject)
            db_controller.create_user(
                    uid=clientInformation.modelObject.uid,
                    callsign=clientInformation.modelObject.detail.contact.callsign,
                    IP=clientInformation.IP,
                    CoT=CoT_row,
                    CN=cn,
                )
        except Exception as ex:
            self.logger.debug("exception thrown adding client to db %s", ex)
            
    def create_iam_request(self, connection: SSLConnection):
        """register the client with the IAM component

        Args:
            connection (SSLConnection): connection object of new client
        """
        request = ObjectFactory.get_new_instance("request")
        request.set_action("connection")
        request.set_sender(self.__class__.__name__.lower())
        request.set_value("connection", connection)
        request.set_format("pickled")
        return request

    def create_send_repeated_messages_request(self, connection: SSLConnection):
        """send the repeated messages to the new client with the repeated messages components

        Args:
            connection (SSLConnection): connection object of new client
        """
        request = ObjectFactory.get_new_instance("request")
        request.set_sender(self.__class__.__name__.lower())
        request.set_action("connection")
        request.set_context("Repeater")
        request.set_value("connection", connection)
        request.set_value("recipients", [str(connection.get_oid())])
        request.set_format("pickled")
        return request
        

    def create_send_emergencies_request(self, connection: SSLConnection):
        """send the active emergencies to the new client with the emergencies component

        Args:
            connection (SSLConnection): connection object of new client
        """
        request = ObjectFactory.get_new_instance("request")
        request.set_action("SendEmergenciesToClient")
        request.set_sender(self.__class__.__name__.lower())
        request.set_value("user", connection)
        request.set_format("pickled")
        return request

    def send_user_connection_geo_chat(self, clientInformation):
        """function to create and send pm to newly connected user

        :param clientInformation: the object containing information about the user to which the msg is sent
        :return:
        """
        # TODO: refactor as it has a proper implementation of a PM to a user generated by the server
        from FreeTAKServer.core.SpecificCoTControllers.SendGeoChatController import (
            SendGeoChatController,
        )
        from FreeTAKServer.model.FTSModel.Dest import Dest
        import uuid

        if OrchestratorConstants().DEFAULTCONNECTIONGEOCHATOBJ != None:
            ChatObj = RawCoT()
            ChatObj.xmlString = f"<event><point/><detail><remarks>{OrchestratorConstants().DEFAULTCONNECTIONGEOCHATOBJ}</remarks><marti><dest/></marti></detail></event>"

            classobj = SendGeoChatController(ChatObj, AddToDB=False)
            instobj = classobj.getObject()
            instobj.modelObject.detail._chat.chatgrp.setuid1(
                clientInformation.modelObject.uid
            )
            dest = Dest()
            dest.setcallsign(clientInformation.modelObject.detail.contact.callsign)
            instobj.modelObject.detail.marti.setdest(dest)
            instobj.modelObject.detail._chat.setchatroom(
                clientInformation.modelObject.detail.contact.callsign
            )
            instobj.modelObject.detail._chat.setparent("RootContactGroup")
            instobj.modelObject.detail._chat.setid(clientInformation.modelObject.uid)
            instobj.modelObject.detail._chat.setgroupOwner("True")
            instobj.modelObject.detail.remarks.setto(clientInformation.modelObject.uid)
            instobj.modelObject.setuid(
                "GeoChat."
                + "SERVER-UID."
                + clientInformation.modelObject.detail.contact.callsign
                + "."
                + str(uuid.uuid1())
            )
            instobj.modelObject.detail._chat.chatgrp.setid(
                clientInformation.modelObject.uid
            )
            classobj.reloadXmlString()
            # self.get_client_information()
            SendDataController().sendDataInQueue(
                    None,
                    instobj,  # pylint: disable=no-member; isinstance checks that CoTOutput is of proper type
                    self.client_information_queue,
                    None,
                )