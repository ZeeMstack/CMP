import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

QUALITY_DISPOSITION_EVENT_KINDS = (
    "RECEIVED_QUARANTINED", "RELEASED", "HELD", "HOLD_RELEASED", "REJECTED", "REVERSAL",
)


class QualityDispositionEvent(Base):
    """STORE-INV-002A.1 schema foundation for `docs/domain/
    STORE_INVENTORY_MODEL.md` §11 -- targets `InventoryQuantityCohort`,
    never `GoodsReceiptLine`/`InventoryLot` directly, since a single receipt
    line's quantity may later be split into differently-usable partitions.

    `.1` writes ONLY the automatic `RECEIVED_QUARANTINED` opening event (as
    part of the atomic receipt transaction, when `qc_release_required`) --
    no human command exists until `STORE-INV-002A.2`. The automatic opening
    event is a system/receipt fact, not a human decision, and is NEVER a
    valid `REVERSAL` target -- enforced here at the database layer
    (`enforce_quality_disposition_event_insert_integrity`), independent of
    and in addition to the fact that `.1` exposes no route that could even
    attempt it. No reversal-of-reversal (a `REVERSAL` can never itself be
    the target of another `REVERSAL`), at most one reversal per target,
    append-only, no hard delete."""

    __tablename__ = "quality_disposition_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    inventory_quantity_cohort_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_quantity_cohorts.id"), nullable=False
    )
    event_kind: Mapped[str] = mapped_column(String, nullable=False)
    reverses_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quality_disposition_events.id"), nullable=True
    )
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    client_command_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String, nullable=True)
    # STORE-INV-002A.2 CTO closure pass (abcdb6f371f9): the owning
    # InventoryQualityCommand -- NULL only for the automatic, receipt-time
    # RECEIVED_QUARANTINED opening fact (a system fact, never an
    # independent human command); NOT NULL for every event any `.2`
    # command has ever written. Tenant-wide command idempotency lives on
    # `InventoryQualityCommand.client_command_id`, never on this table.
    command_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_quality_commands.id"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('RECEIVED_QUARANTINED', 'RELEASED', 'HELD', 'HOLD_RELEASED', "
            "'REJECTED', 'REVERSAL')",
            name="ck_quality_disposition_events_kind_allowed",
        ),
        CheckConstraint(
            "(event_kind = 'REVERSAL' AND reverses_event_id IS NOT NULL) "
            "OR (event_kind <> 'REVERSAL' AND reverses_event_id IS NULL)",
            name="ck_quality_disposition_events_reversal_shape",
        ),
        CheckConstraint(
            "event_kind <> 'REVERSAL' OR reason IS NOT NULL",
            name="ck_quality_disposition_events_reversal_reason_required",
        ),
        # STORE-INV-002A.2 CTO closure pass (abcdb6f371f9): every row except
        # the automatic RECEIVED_QUARANTINED opening fact must carry its
        # owning command.
        CheckConstraint(
            "(event_kind = 'RECEIVED_QUARANTINED' AND command_id IS NULL) OR "
            "(event_kind <> 'RECEIVED_QUARANTINED' AND command_id IS NOT NULL)",
            name="ck_quality_disposition_events_command_id_matches_kind",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_quality_disposition_events_tenant_id_id"),
        # At most one automatic opening event per cohort.
        Index(
            "ux_quality_disposition_events_cohort_opening_quarantine", "inventory_quantity_cohort_id",
            unique=True, postgresql_where=text("event_kind = 'RECEIVED_QUARANTINED'"),
        ),
        # At most one reversal per target event.
        Index(
            "ux_quality_disposition_events_reversal_target", "reverses_event_id", unique=True,
            postgresql_where=text("event_kind = 'REVERSAL'"),
        ),
        ForeignKeyConstraint(
            ["tenant_id", "inventory_quantity_cohort_id"],
            ["inventory_quantity_cohorts.tenant_id", "inventory_quantity_cohorts.id"],
            name="fk_quality_disposition_events_tenant_cohort",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reverses_event_id"],
            ["quality_disposition_events.tenant_id", "quality_disposition_events.id"],
            name="fk_quality_disposition_events_tenant_reversal_target",
        ),
    )
