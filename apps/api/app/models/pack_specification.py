import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PackSpecification(Base):
    """POSTHARVEST-OPS-001B: the stable, tenant-scoped commercial pack/
    product identity -- the exact sibling of `GradeDefinition` one layer
    up the commercial configuration stack, reusing its exact composite-FK
    idiom for `crop_id`(required)/`variety_id`(nullable = applies across
    varieties, subject to whatever its own VERSION narrows). No Customer/
    SalesOrder/pricing/address/allocation/contract entity is introduced --
    `customer_reference` is deliberately free text; a distinct commercial
    identity for a different customer is simply a different
    PackSpecification with its own reference, never a shared row mutated
    per customer."""

    __tablename__ = "pack_specifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    customer_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ux_pack_specifications_tenant_code_lower", "tenant_id", func.lower(code), unique=True),
        Index(
            "ux_pack_specifications_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        UniqueConstraint("tenant_id", "id", name="uq_pack_specifications_tenant_id"),
        ForeignKeyConstraint(
            ["tenant_id", "crop_id"], ["crops.tenant_id", "crops.id"], name="fk_pack_specifications_tenant_crop"
        ),
        # MATCH SIMPLE (Postgres default): only evaluated when variety_id
        # IS NOT NULL -- mirrors fk_grade_definitions_tenant_crop_variety.
        ForeignKeyConstraint(
            ["tenant_id", "crop_id", "variety_id"],
            ["varieties.tenant_id", "varieties.crop_id", "varieties.id"],
            name="fk_pack_specifications_tenant_crop_variety",
        ),
    )
