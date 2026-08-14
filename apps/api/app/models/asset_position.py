import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin

POSITION_KINDS = ("shelf", "slot")


class AssetPosition(TimestampMixin, Base):
    """Relative positions belonging to a single asset (e.g. trolley shelves
    and slots). Not related to the farm-location hierarchy. `position_kind`
    and `parent_position_id` nullability are tied together by a CHECK
    constraint (shelf <=> root, slot <=> has a parent); cross-row rules
    (parent must be a shelf, parent must belong to the same asset, asset
    type must support positions) need a row lookup and are enforced by a
    PostgreSQL trigger in the migration."""

    __tablename__ = "asset_positions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"), nullable=False)
    parent_position_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_positions.id"), nullable=True
    )
    position_kind: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # DOMAIN-FARM-002: see Location.capacity docstring -- identical semantics.
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "position_kind IN ('shelf', 'slot')", name="ck_asset_positions_kind_allowed"
        ),
        CheckConstraint(
            "(position_kind = 'shelf' AND parent_position_id IS NULL) OR "
            "(position_kind = 'slot' AND parent_position_id IS NOT NULL)",
            name="ck_asset_positions_kind_matches_parent",
        ),
        CheckConstraint("capacity IS NULL OR capacity >= 1", name="ck_asset_positions_capacity_positive"),
        Index(
            "ux_asset_positions_sibling_code_lower",
            "parent_position_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_position_id IS NOT NULL"),
        ),
        Index(
            "ux_asset_positions_root_code_lower",
            "asset_id",
            func.lower(code),
            unique=True,
            postgresql_where=text("parent_position_id IS NULL"),
        ),
    )
