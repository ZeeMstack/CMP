import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GoodsReceipt(Base):
    """STORE-INV-002A.1: a Farm-scoped receiving transaction header --
    receiving is physical, happens at one Farm (`docs/domain/
    STORE_INVENTORY_MODEL.md` §E). Pure provenance: immutable once posted,
    no Draft state, no update path. `farm_id` records where this delivery
    was received -- provenance, never current custody (§P)."""

    __tablename__ = "goods_receipts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    received_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String, nullable=True)
    external_system: Mapped[str | None] = mapped_column(String, nullable=True)
    external_document_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("ux_goods_receipts_farm_code_lower", "farm_id", func.lower(code), unique=True),
        Index("ux_goods_receipts_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        UniqueConstraint("tenant_id", "id", name="uq_goods_receipts_tenant_id_id"),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_goods_receipts_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_goods_receipts_tenant_farm"
        ),
    )
