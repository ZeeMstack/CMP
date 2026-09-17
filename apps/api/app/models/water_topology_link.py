"""PILOT-WATER-001A section 5: effective-dated water TOPOLOGY connections.

Four explicit, typed link tables -- deliberately not one generic graph-edge
table (ticket: "Prefer explicit domain entities over an unconstrained
generic graph") -- one per real relationship the ticket names:

    WaterSource       -> Reservoir            (WaterSourceReservoirLink)
    Reservoir         -> IrrigationCircuit    (ReservoirCircuitLink)
    IrrigationCircuit -> WaterDeliveryPoint   (CircuitDeliveryPointLink)
    WaterReturnPoint  -> Reservoir (return)   (ReturnPointReservoirLink)

A link is never updated or deleted once effective -- to answer "what was
connected to what on September 20" the full effective-dated history must
survive every later re-plumbing. Closing a link (superseding it with a new
one) is a service-layer operation that sets `effective_to` on the old row
and inserts a new one in the same transaction; nothing here allows an
UPDATE that would erase the old target.

Each table enforces "at most one ACTIVE (`effective_to IS NULL`) link" on
whichever side the physical plumbing makes exclusive at any one time: a
Reservoir draws from one Source at a time, a Circuit draws from one
Reservoir at a time, a Delivery Point is served by one Circuit at a time,
and a Return Point drains to one Return Reservoir at a time. The other
side is deliberately NOT constrained -- one Reservoir may feed several
Circuits, one Circuit may serve several Delivery Points, and one Return
Reservoir may receive from several Return Points, matching real plumbing.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class _EffectiveDatedLinkMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WaterSourceReservoirLink(_EffectiveDatedLinkMixin, Base):
    __tablename__ = "water_source_reservoir_links"

    water_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("water_sources.id"), nullable=False)
    reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_water_source_reservoir_links_to_after_from",
        ),
        Index(
            "ux_water_source_reservoir_links_active_reservoir", "reservoir_id", unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_source_id"],
            ["water_sources.tenant_id", "water_sources.farm_id", "water_sources.id"],
            name="fk_water_source_reservoir_links_tenant_farm_source",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_water_source_reservoir_links_tenant_farm_reservoir",
        ),
    )


class ReservoirCircuitLink(_EffectiveDatedLinkMixin, Base):
    __tablename__ = "reservoir_circuit_links"

    reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)
    irrigation_circuit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("irrigation_circuits.id"), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_reservoir_circuit_links_to_after_from",
        ),
        Index(
            "ux_reservoir_circuit_links_active_circuit", "irrigation_circuit_id", unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_reservoir_circuit_links_tenant_farm_reservoir",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_reservoir_circuit_links_tenant_farm_circuit",
        ),
    )


class CircuitDeliveryPointLink(_EffectiveDatedLinkMixin, Base):
    __tablename__ = "circuit_delivery_point_links"

    irrigation_circuit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("irrigation_circuits.id"), nullable=False)
    water_delivery_point_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("water_delivery_points.id"), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_circuit_delivery_point_links_to_after_from",
        ),
        Index(
            "ux_circuit_delivery_point_links_active_delivery_point", "water_delivery_point_id", unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "irrigation_circuit_id"],
            ["irrigation_circuits.tenant_id", "irrigation_circuits.farm_id", "irrigation_circuits.id"],
            name="fk_circuit_delivery_point_links_tenant_farm_circuit",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_delivery_point_id"],
            ["water_delivery_points.tenant_id", "water_delivery_points.farm_id", "water_delivery_points.id"],
            name="fk_circuit_delivery_point_links_tenant_farm_delivery_point",
        ),
    )


class ReturnPointReservoirLink(_EffectiveDatedLinkMixin, Base):
    """Drainage/Return Point -> Return Reservoir. Only meaningful for a
    recirculating system -- a drain-to-waste Return Point simply never
    gets a row here (section 7)."""

    __tablename__ = "return_point_reservoir_links"

    water_return_point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("water_return_points.id"), nullable=False)
    return_reservoir_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reservoirs.id"), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="ck_return_point_reservoir_links_to_after_from",
        ),
        Index(
            "ux_return_point_reservoir_links_active_return_point", "water_return_point_id", unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "water_return_point_id"],
            ["water_return_points.tenant_id", "water_return_points.farm_id", "water_return_points.id"],
            name="fk_return_point_reservoir_links_tenant_farm_return_point",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "return_reservoir_id"],
            ["reservoirs.tenant_id", "reservoirs.farm_id", "reservoirs.id"],
            name="fk_return_point_reservoir_links_tenant_farm_return_reservoir",
        ),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_return_point_reservoir_links_tenant_farm_id"),
    )
