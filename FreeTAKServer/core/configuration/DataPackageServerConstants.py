import os
import pathlib
from FreeTAKServer.core.configuration.MainConfig import MainConfig

# Make a connection to the MainConfig object for all routines below
config = MainConfig.instance()

class DataPackageServerConstants:
    def __init__(self):
        # http server config
        self.DATABASE = 'FreeTAKServerDataPackageDataBase.db'
        self.APIPORT = '8080'
        self.DEFAULTRETURN = 'other'
        self.GET = 'GET'
        self.PUT = 'PUT'
        self.POST = 'POST'
        self.DATAPACKAGEFOLDER = 'FreeTAKServerDataPackageFolder'
        self.HTTPDEBUG = False
        self.HTTPMETHODS = ['POST', 'GET', 'PUT']
        self.IP = "0.0.0.0"
        self.versionInfo = config.version
        self.NodeID = 'FTS'
        # version string shown by TAK clients (Marti /api/version/config),
        # derived from the real release version instead of a hardcoded label
        self.VERSIONJSON = '{"version":"3","type":"ServerConfig","data":{"version":"%s-FTS-RELEASE","api":"3","hostname":"%s"},"nodeId":"%s"}' % (
            config.version.replace("FreeTAKServer-", ""), "0.0.0.0", config.nodeID)
