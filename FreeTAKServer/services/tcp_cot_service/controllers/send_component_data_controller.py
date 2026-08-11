import re
from typing import Dict

from FreeTAKServer.services.tcp_cot_service.model.tcp_cot_connection import TCPCoTConnection
from ..configuration.tcp_cot_service_constants import MessageTypes

from digitalpy.core.main.controller import Controller

from FreeTAKServer.core.configuration.ChannelConstants import (
    channels_intersect,
    parse_channels,
)

# uid of the client a CoT message originated from
_UID_PATTERN = re.compile(rb'uid="([^"]+)"')

import logging

class SendComponentDataController(Controller):
    def __init__(self, logger) -> None:
        self.logger = logger

    def send_message(self, connections, message, recipients, uid_channels=None, **kwargs):
        message_type = self.determine_message_type(recipients)
        if message_type == MessageTypes.SEND_TO_ALL:
            self.send_message_to_all(connections, message, uid_channels)
        
        elif message_type == MessageTypes.SEND_TO_SOME:
            self.send_message_to_some(connections, message, recipients)

    def determine_message_type(self, recipients) -> MessageTypes:
        """determine whether the message is to be sent to all or only
        some connections based on the value of recipients

        Returns:
            MessageTypes: _description_
        """
        if recipients is None or recipients == []:
            return MessageTypes.SEND_TO_ALL
        else:
            return MessageTypes.SEND_TO_SOME
    
    def send_message_to_some(self, connections:Dict[str, TCPCoTConnection], message: bytes, recipients):
        """send a given message to some connections based on value of recipients

        Args:
            connections (dict[str, TCPCoTConnection]): a dictionary of connections indexed by their OIDs
            message (bytes): the message to be sent to some clients
        """
        
        for oid in recipients:
            connection = connections.get(oid)
            if connection != None:
                self.logger.debug("sending: %s, to: %s", str(message), str(connection))
                try:
                    connection.sock.send(message)
                except TimeoutError:
                    self.logger.debug("failed to send message to %s with timeout error", str(connection.get_oid()))
                except BrokenPipeError:
                    self.logger.warning("failed to send message to %s with broken pipe error", str(connection.get_oid()))
                except OSError as os_err:
                    self.logger.warning("failed to send message to %s with os error %s", str(connection.get_oid()), str(os_err))

    def send_message_to_all(self, connections:Dict[str, TCPCoTConnection], message: bytes, uid_channels=None):
        """send a message to all connections

        Args:
            connections (dict[str, TCPCoTConnection]): a dictionary of connections indexed by their OIDs
            message (bytes): the message to be sent to some clients
        """
        self.logger.debug("sending %s to %s", message, connections)
        origin_channels = self.get_origin_channels(connections, message, uid_channels)
        for connection in connections.values():
            # component output is relayed to every connection, so channel
            # membership has to be enforced here as well as in the direct
            # client to client path
            if not channels_intersect(
                origin_channels, parse_channels(getattr(connection, "channels", None))
            ):
                continue
            try:
                connection.sock.send(message)
            except TimeoutError:
                self.logger.debug("failed to send message to %s with timeout error", str(connection.get_oid()))
            except BrokenPipeError:
                self.logger.warning("failed to send message to %s with broken pipe error", str(connection.get_oid()))
            except OSError as os_err:
                self.logger.warning("failed to send message to %s with os error %s", str(connection.get_oid()), str(os_err))

    @staticmethod
    def get_origin_channels(connections, message, uid_channels=None):
        """Channels of the client a message originated from.

        The originating client is identified by the uid carried in the CoT
        message; messages the server itself generates match no connection and
        are treated as public so that server traffic still reaches everyone.
        """
        if isinstance(message, str):
            message = message.encode()
        match = _UID_PATTERN.search(message or b"")
        if not match:
            return None
        uid = match.group(1).decode(errors="replace")
        if uid_channels and uid in uid_channels:
            return uid_channels[uid]
        for connection in connections.values():
            model_object = getattr(connection, "model_object", None)
            if model_object is not None and getattr(model_object, "uid", None) == uid:
                return parse_channels(getattr(connection, "channels", None))
        return None
