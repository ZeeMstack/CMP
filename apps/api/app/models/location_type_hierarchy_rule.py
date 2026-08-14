import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class LocationTypeHierarchyRule(Base):
    """Permitted parent-child location-type combinations. `parent_type_id`
    NULL means the child type may be a farm-root location.

    DOMAIN-FARM-001: `greenhouse_classification` scopes a rule to one of the
    three approved greenhouse classifications. `NULL` means the rule is
    generic (applies outside any greenhouse tree, or at farm-root level).
    Rows are never mixed: `location_service._validate_hierarchy` looks up
    ONLY classification-matching rows when the candidate parent resolves to
    inside a classified greenhouse, and ONLY `NULL`-classification (generic)
    rows otherwise — there is no fallback from one to the other.

    A normal nullable composite unique constraint would allow unlimited
    duplicate NULL-parent rows (Postgres treats NULL as distinct), so
    uniqueness is split across partial indexes instead."""

    __tablename__ = "location_type_hierarchy_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_types.id"), nullable=True
    )
    child_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("location_types.id"), nullable=False
    )
    greenhouse_classification: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "greenhouse_classification IS NULL OR greenhouse_classification IN "
            "('nursery', 'leafy_greens', 'vines')",
            name="ck_location_type_hierarchy_rules_classification_allowed",
        ),
        CheckConstraint(
            "greenhouse_classification IS NULL OR parent_type_id IS NOT NULL",
            name="ck_location_type_hierarchy_rules_scoped_requires_parent",
        ),
        Index(
            "ux_location_type_hierarchy_generic_parent_child",
            "parent_type_id",
            "child_type_id",
            unique=True,
            postgresql_where=text("greenhouse_classification IS NULL AND parent_type_id IS NOT NULL"),
        ),
        Index(
            "ux_location_type_hierarchy_generic_root_child",
            "child_type_id",
            unique=True,
            postgresql_where=text("greenhouse_classification IS NULL AND parent_type_id IS NULL"),
        ),
        Index(
            "ux_location_type_hierarchy_scoped",
            "greenhouse_classification",
            "parent_type_id",
            "child_type_id",
            unique=True,
            postgresql_where=text("greenhouse_classification IS NOT NULL"),
        ),
    )
