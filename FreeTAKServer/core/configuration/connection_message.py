"""The message a client is greeted with when it connects.

Kept in a file of its own rather than in the settings each process loaded at
startup, because the process that changes it is not the one that sends it:
the API answers the browser, the CoT services greet the clients. Reading the
file as a client connects means a new message takes effect straight away.
"""
import os

from FreeTAKServer.core.configuration.MainConfig import MainConfig

config = MainConfig.instance()

MESSAGE_FILE = os.path.join(os.environ.get("FTS_PERSISTENCE_PATH", "/opt/fts"), "connection_message.txt")


def connection_message():
    """What to greet a client with, or None to greet it with nothing."""
    try:
        with open(MESSAGE_FILE) as handle:
            message = handle.read().strip()
    except OSError:
        return config.ConnectionMessage
    return message or None


def set_connection_message(message):
    """Set what clients are greeted with. An empty message greets them with nothing."""
    text = (message or "").strip()
    os.makedirs(os.path.dirname(MESSAGE_FILE), exist_ok=True)
    with open(MESSAGE_FILE, "w") as handle:
        handle.write(text)
    return text or None
