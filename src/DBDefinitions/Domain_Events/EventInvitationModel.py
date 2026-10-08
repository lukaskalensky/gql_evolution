import datetime
from typing import Optional
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from src.DBDefinitions.BaseModel import BaseDBModel, UUIDColumn, UUIDFKey, IDType
###########################################################################################################################
#
# zde definujte sve SQLAlchemy modely
# je-li treba, muzete definovat modely obsahujici jen id polozku, na ktere se budete odkazovat
#
###########################################################################################################################

class EventInvitationModel(BaseDBModel):
    __tablename__ = "event_invitations"

    id: Mapped[IDType] = mapped_column(primary_key=True, default=None, nullable=True)
    
    event_id: Mapped[Optional[IDType]] = mapped_column(ForeignKey("events.id"), default=None, nullable=True, comment="Event assigned to the invitation")
    user_id: Mapped[Optional[IDType]] = UUIDFKey(ForeignKey("users.id"), default=None, nullable=True, comment="User assigned to the invitation")
    state_id: Mapped[Optional[IDType]] = UUIDFKey(ForeignKey("states.id"), default=None, nullable=True, comment="State assigned to the invitation")
    
    # Relationships: viewonly indicates that these relationships are loaded via foreign keys.
    event = relationship(
        "EventModel",
        primaryjoin="EventInvitationModel.event_id==EventModel.id",
        uselist=False,
        viewonly=True
    )


#                         +-------------+
#                         |  organizer  |
#                         +-------------+
#                                |
#                                v
# +----------+   accept    +-----------+  attend   +-----------+
# | invited  | ----------> | accepted  | --------> | attended  |
# +----------+             +-----------+           +-----------+
#       |                        |
#       | decline                | excuse
#       v                        v
# +-----------+             +-----------+
# | declined  |             |  excused  |
# +-----------+             +-----------+
#
#   ('01b96c1d-8389-4267-a859-d8116e1c32f3', 'invited',   'Pozván',        'Uživatel byl pozván na událost', true,  false),
#   ('7d2ef223-b60e-4e6d-b7d5-5fdc1f8e2ec2', 'accepted',  'Přijal',        'Uživatel potvrdil účast',        false, false),
#   ('d6a5e9e4-3e47-4c95-a4aa-b194dd2bc3a7', 'declined',  'Odmítl',        'Uživatel odmítl účast',          false, true),
#   ('d7c38ef9-c7d0-4ff9-a72e-fd1e0b70f387', 'attended',  'Účastnil se',   'Uživatel se účastnil události',  false, true),
#   ('b0b2df1d-4e67-47c3-9c68-4d25a0e0a01a', 'excused',   'Omluven',       'Uživatel se omluvil z účasti',   false, true),
#   ('3265a488-bbfa-4c59-946c-7a7b059ee4f0', 'organizer', 'Organizátor',   'Uživatel je organizátorem akce', false, false);
