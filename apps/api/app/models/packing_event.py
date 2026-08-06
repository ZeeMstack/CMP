import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PackingEvent(Base):
    """Immutable, insert-only record of one packing command (CMP-015): the
    first typed consumer of produce-lot ledger balances. Consumes one or
    more harvested produce lots (each recorded as an immutable
    `PackingInputLine` plus a deterministic `packing_consumption` ledger
    debit) and creates exactly one `FinishedGoodsLot`. Reconciliation
    (`total_input = packed_output + process_loss + rejected`) is enforced
    as a same-row CHECK constraint, not just at write time."""

    __tablename__ = "packing_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    crop_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crops.id"), nullable=False)
    variety_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("varieties.id"), nullable=True)
    total_input_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    packed_output_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    process_loss_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    rejected_weight_kg: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "total_input_weight_kg > 0 AND total_input_weight_kg = trunc(total_input_weight_kg, 3) "
            "AND total_input_weight_kg < 100000000000",
            name="ck_packing_events_total_input_envelope",
        ),
        CheckConstraint(
            "packed_output_weight_kg > 0 AND packed_output_weight_kg = trunc(packed_output_weight_kg, 3) "
            "AND packed_output_weight_kg < 100000000000",
            name="ck_packing_events_packed_output_positive",
        ),
        CheckConstraint(
            "process_loss_weight_kg >= 0 AND process_loss_weight_kg = trunc(process_loss_weight_kg, 3) "
            "AND process_loss_weight_kg < 100000000000",
            name="ck_packing_events_process_loss_envelope",
        ),
        CheckConstraint(
            "rejected_weight_kg >= 0 AND rejected_weight_kg = trunc(rejected_weight_kg, 3) "
            "AND rejected_weight_kg < 100000000000",
            name="ck_packing_events_rejected_envelope",
        ),
        # Same-row, immutable-function reconciliation — a defense-in-depth
        # complement to the deferred cross-table packing-reconciliation
        # trigger, which additionally proves the event's totals equal the
        # sum of its own input lines.
        CheckConstraint(
            "total_input_weight_kg = packed_output_weight_kg + process_loss_weight_kg + rejected_weight_kg",
            name="ck_packing_events_reconciliation",
        ),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_packing_events_tenant_farm_id"),
        Index("ux_packing_events_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
    )
