from FreeTAKServer.core.persistence.table_controllers import TableController
from FreeTAKServer.model.SQLAlchemy.channel import Channel


class ChannelTableController(TableController):

    def __init__(self):
        self.table = Channel
