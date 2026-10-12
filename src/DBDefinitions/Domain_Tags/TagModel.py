from typing import Optional, List
from sqlalchemy import String
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

    tag_entities: Mapped[List["TagEntityModel"]] = relationship(
        "TagEntityModel",
        back_populates="tag",
        uselist=True,
        init=False,
    )
