from typing import Optional, List
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.DBDefinitions.BaseModel import BaseDBModel, IDType


class TagTypeModel(BaseDBModel):
    """Represents a tag type (category) as a tree node, e.g. Priorita -> Vysoká priorita.

    Číselník typů tagů je implementován jako strom (typy typů) pomocí parent_id.
    """
    __tablename__ = "tagtypes"

    path_attribute_name = "path"
    parent_attribute_name = "parent"
    parent_id_attribute_name = "parent_id"
    children_attribute_name = "children"

    # Materialized path technique
    path: Mapped[Optional[str]] = mapped_column(
        String,
        index=True,
        nullable=True,
        default=None,
        comment="Materialized path technique, not implemented"
    )

    name: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="název typu tagu"
    )
    name_en: Mapped[Optional[str]] = mapped_column(
        String,
        default=None,
        nullable=True,
        comment="anglický název typu tagu"
    )

    parent_id: Mapped[Optional[IDType]] = mapped_column(
        ForeignKey("tagtypes.id"),
        index=True,
        nullable=True,
        default=None,
        comment="nadřazený typ tagu (kořen stromu má None)"
    )

    parent: Mapped[Optional["TagTypeModel"]] = relationship(
        "TagTypeModel",
        back_populates="children",
        remote_side="TagTypeModel.id",
        uselist=False,
        init=False,
    )

    children: Mapped[List["TagTypeModel"]] = relationship(
        "TagTypeModel",
        back_populates="parent",
        uselist=True,
        init=False,
    )

    tags: Mapped[List["TagModel"]] = relationship(
        "TagModel",
        back_populates="type",
        viewonly=True,
        uselist=True,
        init=False,
    )
