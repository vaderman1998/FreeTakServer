from sqlalchemy import Column, String

from FreeTAKServer.model.SQLAlchemy.Root import Base


class Channel(Base):
    """A named channel that CoT traffic can be confined to.

    Membership lives on SystemUser.channels; this table exists so channels
    can be created, described and listed before anyone is assigned to them.
    """

    __tablename__ = 'Channel'
    uid = Column(String(80), primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(String(255), nullable=True, default=None)

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            if hasattr(value, '__iter__') and not isinstance(value, str):
                value = value[0]
            setattr(self, property, value)

    def __repr__(self):
        return str(self.name)
