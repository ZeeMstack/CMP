import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class CarrierSpecification(TimestampMixin, Base):
    """CARRIER-CONFIG-001: a tenant-configurable reusable physical design
    for a CarrierType -- e.g. CarrierType=seed_tray, specification="200 Cell
    Tray". Sits between the platform-defined `CarrierType` (a role) and the
    individually-traceable `Carrier` (a physical object); a Carrier
    optionally references one specification via `Carrier.specification_id`.

    Physical equipment configuration only -- never a crop/variety/planting-
    density fact (those belong to a future, separate crop/workflow
    specification concept). `biological_position_count` is the physical
    cell/hole count of the reusable DESIGN, deliberately independent of
    `SowingEventLine.sown_site_count`/`seed_count` (operational, per-sowing
    facts) and of `TransplantDestinationLine.assigned_plant_count`
    (operational, per-cycle fact) -- this model never reads or constrains
    either.

    Dimensions are canonical integer millimeters -- no `dimension_unit`
    column, no conversion framework; display-side unit conversion, if ever
    wanted, is a frontend concern computed from this one stored value.

    Structural fields (`carrier_type_id`, `code`, `length_mm`, `width_mm`,
    `height_mm`, `biological_position_count`) freeze the moment the FIRST
    Carrier references this specification -- enforced in the service layer
    and backstopped by `enforce_carrier_specification_structural_freeze`
    (this migration). `name`/`status` remain editable indefinitely."""

    __tablename__ = "carrier_specifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    carrier_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("carrier_types.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    length_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    biological_position_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_carrier_specifications_status"),
        CheckConstraint(
            "length_mm IS NULL OR length_mm > 0", name="ck_carrier_specifications_length_positive"
        ),
        CheckConstraint(
            "width_mm IS NULL OR width_mm > 0", name="ck_carrier_specifications_width_positive"
        ),
        CheckConstraint(
            "height_mm IS NULL OR height_mm > 0", name="ck_carrier_specifications_height_positive"
        ),
        CheckConstraint(
            "biological_position_count IS NULL OR biological_position_count > 0",
            name="ck_carrier_specifications_position_count_positive",
        ),
        Index("ux_carrier_specifications_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_carrier_specifications_tenant_id_id"),
    )
