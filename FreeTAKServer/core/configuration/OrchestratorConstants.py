
from FreeTAKServer.core.configuration.MainConfig import MainConfig

# Make a connection to the MainConfig object for all routines below
config = MainConfig.instance()

class OrchestratorConstants:
    def __init__(self):
        self.CoTIP = "0.0.0.0"
        self.COTPORT = config.CoTServicePort
        self.APIPORTARG = '-APIPort'
        self.COTPORTARG = '-CoTPort'
        self.IPARG = "-IP"
        self.APIPORTDESC = 'the port address you would like FreeTAKServer to run receive datapackages on not'
        self.IPDESC = "the IP you would like FreeTAKServer to run receive connections on, must be set for private DataPackages to function"
        self.COTPORTDESC = 'the port you would like FreeTAKServer to run receive connections on'
        self.COTIPDESC = 'the IP you would like FreeTAKServer to run receive connections on'
        self.SSLCOTPORTDESC = 'the port you would like FreeTAKServer to run receive SSL connections on'
        self.SSLCOTIPDESC = 'the IP you would like FreeTAKServer to run receive SSL connections on'
        self.FULLDESC = 'FreeTAKServer startup settings'
        self.HEALTHCHECK = 'HealthCheck'
        self.LOCALHOST = '127.0.0.1'

        # read as each client connects, so a message changed from the UI
        # reaches the next client without restarting the server
        from FreeTAKServer.core.configuration.connection_message import connection_message

        self.DEFAULTCONNECTIONGEOCHATOBJ = connection_message()