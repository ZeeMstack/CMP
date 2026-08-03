import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

POSITION_KINDS = ("shelf", "slot")


class OccupancyCompatibilityRule(Base):
    """Global, system-defined occupant/target compatibility rules, seeded by
    migration. Occupant is exactly one of asset type / carrier type; target
    is exactly one of location type / asset-position kind. Four partial
    unique indexes cover each of the four occupant-kind x target-kind
    combinations (a plain composite unique constraint can't dedupe correctly
    across two independently-nullable XOR pairs)."""

    __tablename__ = "occupancy_compatibility_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occupant_asset_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_types.id"), nullable=True
    )
    occupant_carrier_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("carrier_types.id"), nullable=True
    )
    target_location_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("location_types.id"), nullable=True
    )
    target_position_kind: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "(occupant_asset_type_id IS NOT NULL)::int + (occupant_carrier_type_id IS NOT NULL)::int = 1",
            name="ck_occ_compat_rules_occupant_xor",
        ),
        CheckConstraint(
            "(target_location_type_id IS NOT NULL)::int + (target_position_kind IS NOT NULL)::int = 1",
            name="ck_occ_compat_rules_target_xor",
        ),
        CheckConstraint(
            "target_position_kind IS NULL OR target_position_kind IN ('shelf', 'slot')",
            name="ck_occ_compat_rules_position_kind_allowed",
        ),
        Index(
            "ux_occ_compat_asset_location",
            "occupant_asset_type_id",
            "target_location_type_id",
            unique=True,
            postgresql_where=text(
                "occupant_asset_type_id IS NOT NULL AND target_location_type_id IS NOT NULL"
            ),
        ),
        Index(
            "ux_occ_compat_asset_position",
            "occupant_asset_type_id",
            "target_position_kind",
            unique=True,
            postgresql_where=text(
                "occupant_asset_type_id IS NOT NULL AND target_position_kind IS NOT NULL"
            ),
        ),
        Index(
            "ux_occ_compat_carrier_location",
            "occupant_carrier_type_id",
            "target_location_type_id",
            unique=True,
            postgresql_where=text(
                "occupant_carrier_type_id IS NOT NULL AND target_location_type_id IS NOT NULL"
            ),
        ),
        Index(
            "ux_occ_compat_carrier_position",
            "occupant_carrier_type_id",
            "target_position_kind",
            unique=True,
            postgresql_where=text(
                "occupant_carrier_type_id IS NOT NULL AND target_position_kind IS NOT NULL"
            ),
        ),
    )
