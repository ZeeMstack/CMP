import uuid

from sqlalchemy import ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LocationTypeHierarchyRule(Base):
    """Permitted parent-child location-type combinations. `parent_type_id`
    NULL means the child type may be a farm-root location. A normal nullable
    composite unique constraint would allow unlimited duplicate NULL-parent
    rows (Postgres treats NULL as distinct), so uniqueness is split across
    two partial indexes instead."""

    __tablename__ = "location_type_hierarchy_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_types.id"), nullable=True
    )
    child_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("location_types.id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ux_location_type_hierarchy_parent_child",
            "parent_type_id",
            "child_type_id",
            unique=True,
            postgresql_where=text("parent_type_id IS NOT NULL"),
        ),
        Index(
            "ux_location_type_hierarchy_root_child",
            "child_type_id",
            unique=True,
            postgresql_where=text("parent_type_id IS NULL"),
        ),
    )
