from typing import Optional, List
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.DBDefinitions.BaseModel import BaseDBModel, IDType


class TagModel(BaseDBModel):
    """Represents a tag definition."""
    __tablename__ = "tags"

    name: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="interní název tagu"
    )
    label: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="zobrazovaný název"
    )
    color: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="barva tagu"
    )
    description: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="popis významu tagu"
    )
    type_id: Mapped[Optional[IDType]] = mapped_column(
        ForeignKey("tagtypes.id"),
        index=True,
        nullable=True,
        default=None,
        comment="typ tagu (uzel stromu číselníku tagtypes)"
    )

    type: Mapped[Optional["TagTypeModel"]] = relationship(
        "TagTypeModel",
        back_populates="tags",
        viewonly=True,
        uselist=False,
        init=False,
    )

    tag_entities: Mapped[List["TagEntityModel"]] = relationship(
        "TagEntityModel",
        back_populates="tag",
        uselist=True,
        init=False,
    )

#Pridat relationship