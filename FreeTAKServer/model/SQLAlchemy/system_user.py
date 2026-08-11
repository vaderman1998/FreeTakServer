from sqlalchemy import Column
from FreeTAKServer.model.SQLAlchemy.Root import Base
from sqlalchemy import String
from sqlalchemy import Boolean
from sqlalchemy.orm import relationship
from flask_login import UserMixin


class SystemUser(Base, UserMixin):

    __tablename__ = 'SystemUser'
    uid = Column(String(80), primary_key=True)
    name = Column(String(15), nullable=False)
    token = Column(String(30), nullable=True)
    password = Column(String(30), nullable=True)
    # authorization role: "admin" or "user". Kept separate from the channels
    # below, which are the TAK sense of a group.
    role = Column(String(15), nullable=True, default=None)
    # retained so deployments that set a role through the old column keep
    # working; role takes precedence when both are present
    group = Column(String(15), default=True, nullable=True)
    # comma separated channel names this user's CoT traffic is confined to;
    # empty or null means the public channel only
    channels = Column(String(255), nullable=True, default=None)
    device_type = Column(String(30), nullable=False)
    certificate_package_name = Column(String(30), nullable=True, default=None)
    api_calls = relationship("APICalls")

    def __init__(self, **kwargs):
        for property, value in kwargs.items():
            # depending on whether value is an iterable or not, we must
            # unpack it's value (when **kwargs is request.form, some values
            # will be a 1-element list)
            if hasattr(value, '__iter__') and not isinstance(value, str):
                # the ,= unpack of a singleton fails PEP8 (travis flake8 test)
                value = value[0]

            setattr(self, property, value)

    def get_id(self):
        return self.uid

    def __repr__(self):
        return str(self.name)