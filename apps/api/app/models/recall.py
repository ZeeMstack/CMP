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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RecallCase(Base):
    """Immutable, insert-only formal food-safety containment decision
    (CMP-020). The row itself *is* the "opened" fact -- there is no
    separate opened-event row and no mutable status column, mirroring
    `QualityHold`'s own immutable-fact-plus-derived-state shape. Exactly
    one of `crop_batch_id`/`harvested_produce_lot_id`/`finished_goods_lot_id`
    is populated (`ck_recall_cases_typed_source_shape`). Open/closed state
    is always derived from whether a `RecallCaseClosure` row exists."""

    __tablename__ = "recall_cases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    crop_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("crop_batches.id"), nullable=True)
    harvested_produce_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=True
    )
    finished_goods_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("finished_goods_lots.id"), nullable=True
    )
    reason_code: Mapped[str] = mapped_column(String, nullable=False)
    reason_text: Mapped[str] = mapped_column(String, nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN crop_batch_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN harvested_produce_lot_id IS NOT NULL THEN 1 ELSE 0 END) + "
            "(CASE WHEN finished_goods_lot_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
            name="ck_recall_cases_typed_source_shape",
        ),
        Index("ux_recall_cases_tenant_client_command_id", "tenant_id", "client_command_id", unique=True),
        Index("ux_recall_cases_farm_code_lower", "farm_id", func.lower(code), unique=True),
        UniqueConstraint("tenant_id", "farm_id", "id", name="uq_recall_cases_tenant_farm_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id"], ["farms.tenant_id", "farms.id"], name="fk_recall_cases_tenant_farm"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_recall_cases_tenant_farm_batch",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id",
                "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_recall_cases_tenant_farm_produce_lot",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_recall_cases_tenant_farm_fg_lot",
        ),
    )


class RecallCaseClosure(Base):
    """Immutable, insert-only decision ending a recall case's active
    containment -- a separate record, never a mutation of the case, exactly
    mirroring `QualityHoldRelease`. At most one closure per case
    (`ux_recall_case_closures_case`, global single-column unique, the same
    idiom `batch_derivation_sources.source_batch_id` uses). Closing never
    deletes/mutates the case or its frozen scope, never implies product
    recovery or customer notification, and never releases a quality hold."""

    __tablename__ = "recall_case_closures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recall_cases.id"), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    client_command_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    close_reason: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index(
            "ux_recall_case_closures_tenant_client_command_id", "tenant_id", "client_command_id", unique=True
        ),
        Index("ux_recall_case_closures_case", "recall_case_id", unique=True),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_case_closures_tenant_farm_case",
        ),
    )


class RecallScopeBatch(Base):
    """Immutable, insert-only member of a recall case's frozen crop-batch
    scope (CMP-020). Records entity identity only -- never a balance, never
    the recall's own open/closed state. Reverse-lookup index
    (`ix_recall_scope_batches_tenant_farm_batch`) backs every containment
    gate's "is this batch currently contained" query."""

    __tablename__ = "recall_scope_batches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recall_cases.id"), nullable=False)
    crop_batch_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("crop_batches.id"), nullable=False)
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("recall_case_id", "crop_batch_id", name="ux_recall_scope_batches_case_batch"),
        Index("ix_recall_scope_batches_tenant_farm_batch", "tenant_id", "farm_id", "crop_batch_id"),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_batches_tenant_farm_case",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "crop_batch_id"],
            ["crop_batches.tenant_id", "crop_batches.farm_id", "crop_batches.id"],
            name="fk_recall_scope_batches_tenant_farm_batch",
        ),
    )


class RecallScopeProduceLot(Base):
    """Immutable, insert-only member of a recall case's frozen
    harvested-produce-lot scope (CMP-020). See `RecallScopeBatch` for the
    shared design rationale."""

    __tablename__ = "recall_scope_produce_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recall_cases.id"), nullable=False)
    harvested_produce_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("harvested_produce_lots.id"), nullable=False
    )
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "recall_case_id", "harvested_produce_lot_id", name="ux_recall_scope_produce_lots_case_lot"
        ),
        Index(
            "ix_recall_scope_produce_lots_tenant_farm_lot", "tenant_id", "farm_id", "harvested_produce_lot_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_produce_lots_tenant_farm_case",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "harvested_produce_lot_id"],
            [
                "harvested_produce_lots.tenant_id",
                "harvested_produce_lots.farm_id",
                "harvested_produce_lots.id",
            ],
            name="fk_recall_scope_produce_lots_tenant_farm_lot",
        ),
    )


class RecallScopeFinishedGoodsLot(Base):
    """Immutable, insert-only member of a recall case's frozen
    finished-goods-lot scope (CMP-020). See `RecallScopeBatch` for the
    shared design rationale."""

    __tablename__ = "recall_scope_finished_goods_lots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    farm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("farms.id"), nullable=False)
    recall_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recall_cases.id"), nullable=False)
    finished_goods_lot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("finished_goods_lots.id"), nullable=False
    )
    recorded_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "recall_case_id", "finished_goods_lot_id", name="ux_recall_scope_fg_lots_case_lot"
        ),
        Index(
            "ix_recall_scope_fg_lots_tenant_farm_lot", "tenant_id", "farm_id", "finished_goods_lot_id"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "recall_case_id"],
            ["recall_cases.tenant_id", "recall_cases.farm_id", "recall_cases.id"],
            name="fk_recall_scope_fg_lots_tenant_farm_case",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "farm_id", "finished_goods_lot_id"],
            ["finished_goods_lots.tenant_id", "finished_goods_lots.farm_id", "finished_goods_lots.id"],
            name="fk_recall_scope_fg_lots_tenant_farm_lot",
        ),
    )
