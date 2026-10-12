from typing import Optional
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.DBDefinitions.BaseModel import BaseDBModel, UUIDFKey, IDType


class TagEntityModel(BaseDBModel):
    """Represents assignment of a specific tag to an entity."""
    __tablename__ = "tag_entities"

    entity_id: Mapped[Optional[IDType]] = UUIDFKey(
        nullable=True,
        comment="identifikátor označené entity"
    )
    entity_type_id: Mapped[Optional[IDType]] = UUIDFKey(
        nullable=True,
        comment="typ označené entity"
    )
    tag_id: Mapped[Optional[IDType]] = mapped_column(
        ForeignKey("tags.id"),
        index=True,
        nullable=True,
        default=None,
        comment="identifikátor přiřazeného tagu"
    )
    owner_id: Mapped[Optional[IDType]] = UUIDFKey(
        ForeignKey("users.id"),
        nullable=True,
        default=None,
        comment="vlastník tohoto přiřazení"
    )

    tag: Mapped[Optional["TagModel"]] = relationship(
        "TagModel",
        back_populates="tag_entities",
        uselist=False,
        init=False,
    )
