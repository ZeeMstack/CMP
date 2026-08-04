import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.batch_stage_run import BatchStageRun
from app.models.crop_batch import CropBatch
from app.models.observation_event import ObservationEvent
from app.models.quality_hold import QualityHold
from app.models.quality_hold_release import QualityHoldRelease
from app.models.workflow_stage import WorkflowStage
from app.schemas.crop_batch import StageSummary
from app.schemas.quality_hold import QualityHoldRead, QualityHoldReleaseRead
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    CropBatchClosedError,
    CropBatchNotFoundError,
    FarmNotFoundError,
    InvalidQualityHoldEffectiveTimeError,
    ObservationEventNotFoundError,
    QualityHoldAlreadyReleasedError,
    QualityHoldCommandReusedWithDifferentPayloadError,
    QualityHoldNotFoundError,
    QualityHoldValidationError,
)


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _get_batch_row(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID) -> CropBatch:
    batch = db.execute(
        select(CropBatch).where(
            CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id
        )
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))
    return batch


def has_open_quality_hold(db: Session, *, batch_id: uuid.UUID) -> bool:
    """Used by `crop_batch_service.transition_stage` to enforce that stage
    progression is blocked while any quality hold on the batch remains
    unreleased (CMP-010)."""
    open_hold = db.execute(
        select(QualityHold.id).where(
            QualityHold.batch_id == batch_id,
            ~exists().where(QualityHoldRelease.quality_hold_id == QualityHold.id),
        )
    ).first()
    return open_hold is not None


# --- Hold placement -----------------------------------------------------------------


def _compute_hold_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    source_observation_event_id: uuid.UUID | None, effective_time: datetime, reason_code: str, reason_text: str,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id),
        str(source_observation_event_id or ""), effective_time.astimezone(timezone.utc).isoformat(),
        reason_code, reason_text,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_hold(db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID) -> QualityHold | None:
    return db.execute(
        select(QualityHold).where(
            QualityHold.tenant_id == tenant_id, QualityHold.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def place_quality_hold(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    source_observation_event_id: uuid.UUID | None,
    reason_code: str,
    reason_text: str,
) -> QualityHold:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidQualityHoldEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_hold_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id,
        source_observation_event_id=source_observation_event_id, effective_time=effective_time,
        reason_code=reason_code, reason_text=reason_text,
    )

    existing = _find_existing_hold(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_hold(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    active_run = db.execute(
        select(BatchStageRun)
        .where(BatchStageRun.batch_id == batch.id, BatchStageRun.exited_effective_time.is_(None))
        .with_for_update()
    ).scalar_one_or_none()
    if active_run is None:
        raise CropBatchNotFoundError(str(batch_id))

    if effective_time < batch.created_effective_time:
        raise InvalidQualityHoldEffectiveTimeError("effective_time precedes the batch's creation effective time")
    if effective_time < active_run.entered_effective_time:
        raise InvalidQualityHoldEffectiveTimeError("effective_time precedes the current stage run's entry time")

    if source_observation_event_id is not None:
        source = db.execute(
            select(ObservationEvent).where(
                ObservationEvent.id == source_observation_event_id, ObservationEvent.tenant_id == tenant_id,
                ObservationEvent.farm_id == farm_id, ObservationEvent.batch_id == batch.id,
            )
        ).scalar_one_or_none()
        if source is None:
            raise ObservationEventNotFoundError(str(source_observation_event_id))
        if source.effective_time > effective_time:
            raise QualityHoldValidationError(
                "source observation effective time cannot be after the hold effective time"
            )

    hold = QualityHold(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, batch_id=batch.id,
        active_batch_stage_run_id=active_run.id, source_observation_event_id=source_observation_event_id,
        effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint, reason_code=reason_code, reason_text=reason_text,
    )
    db.add(hold)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_quality_holds_tenant_client_command_id":
            replay = _find_existing_hold(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    try:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.quality_hold_placed",
            entity_type="quality_hold", entity_id=hold.id,
            event_data={
                "quality_hold_id": str(hold.id), "batch_id": str(batch.id),
                "batch_stage_run_id": str(active_run.id),
                "source_observation_event_id": str(source_observation_event_id)
                if source_observation_event_id
                else None,
                "effective_time": effective_time.isoformat(), "client_command_id": str(client_command_id),
                "reason_code": reason_code,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(hold)
    return hold


# --- Hold release -------------------------------------------------------------------


def _compute_release_fingerprint(
    *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, batch_id: uuid.UUID,
    hold_id: uuid.UUID, effective_time: datetime, release_reason: str,
) -> str:
    parts = [
        str(tenant_id), str(farm_id), str(actor_user_id), str(batch_id), str(hold_id),
        effective_time.astimezone(timezone.utc).isoformat(), release_reason,
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _find_existing_release(
    db: Session, *, tenant_id: uuid.UUID, client_command_id: uuid.UUID
) -> QualityHoldRelease | None:
    return db.execute(
        select(QualityHoldRelease).where(
            QualityHoldRelease.tenant_id == tenant_id, QualityHoldRelease.client_command_id == client_command_id
        )
    ).scalar_one_or_none()


def release_quality_hold(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    batch_id: uuid.UUID,
    hold_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    release_reason: str,
) -> QualityHoldRelease:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    if effective_time > datetime.now(timezone.utc):
        raise InvalidQualityHoldEffectiveTimeError("effective_time cannot be in the future")

    fingerprint = _compute_release_fingerprint(
        tenant_id=tenant_id, farm_id=farm_id, actor_user_id=actor_user_id, batch_id=batch_id, hold_id=hold_id,
        effective_time=effective_time, release_reason=release_reason,
    )

    existing = _find_existing_release(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id))

    batch = db.execute(
        select(CropBatch)
        .where(CropBatch.id == batch_id, CropBatch.tenant_id == tenant_id, CropBatch.farm_id == farm_id)
        .with_for_update()
    ).scalar_one_or_none()
    if batch is None:
        raise CropBatchNotFoundError(str(batch_id))

    existing = _find_existing_release(db, tenant_id=tenant_id, client_command_id=client_command_id)
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id))

    if batch.state != "active":
        raise CropBatchClosedError(str(batch_id))

    hold = db.execute(
        select(QualityHold)
        .where(QualityHold.id == hold_id, QualityHold.tenant_id == tenant_id, QualityHold.farm_id == farm_id,
               QualityHold.batch_id == batch.id)
        .with_for_update()
    ).scalar_one_or_none()
    if hold is None:
        raise QualityHoldNotFoundError(str(hold_id))

    already_released = db.execute(
        select(QualityHoldRelease.id).where(QualityHoldRelease.quality_hold_id == hold.id)
    ).scalar_one_or_none()
    if already_released is not None:
        raise QualityHoldAlreadyReleasedError(str(hold_id))

    if effective_time < hold.effective_time:
        raise InvalidQualityHoldEffectiveTimeError("release effective_time cannot precede the hold effective_time")

    release = QualityHoldRelease(
        id=uuid.uuid4(), tenant_id=tenant_id, farm_id=farm_id, quality_hold_id=hold.id, batch_id=batch.id,
        effective_time=effective_time, actor_user_id=actor_user_id, client_command_id=client_command_id,
        request_fingerprint=fingerprint, release_reason=release_reason,
    )
    db.add(release)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        constraint = _constraint_name(exc)
        if constraint == "ux_quality_hold_releases_tenant_client_command_id":
            replay = _find_existing_release(db, tenant_id=tenant_id, client_command_id=client_command_id)
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise QualityHoldCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        if constraint == "ux_quality_hold_releases_hold":
            raise QualityHoldAlreadyReleasedError(str(hold_id)) from exc
        raise

    try:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="crop_batch.quality_hold_released",
            entity_type="quality_hold", entity_id=hold.id,
            event_data={
                "quality_hold_release_id": str(release.id), "quality_hold_id": str(hold.id),
                "batch_id": str(batch.id), "effective_time": effective_time.isoformat(),
                "client_command_id": str(client_command_id),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(release)
    return release


# --- Reads ------------------------------------------------------------------------


def _hold_detail_query():
    return (
        select(QualityHold, WorkflowStage)
        .join(BatchStageRun, BatchStageRun.id == QualityHold.active_batch_stage_run_id)
        .join(WorkflowStage, WorkflowStage.id == BatchStageRun.workflow_stage_id)
    )


def _row_to_hold_read(row, release: QualityHoldRelease | None) -> QualityHoldRead:
    hold: QualityHold = row[0]
    stage: WorkflowStage = row[1]
    return QualityHoldRead(
        id=hold.id, tenant_id=hold.tenant_id, farm_id=hold.farm_id, batch_id=hold.batch_id,
        stage=StageSummary(id=stage.id, code=stage.code, name=stage.name, is_terminal=stage.is_terminal),
        source_observation_event_id=hold.source_observation_event_id, effective_time=hold.effective_time,
        recorded_time=hold.recorded_time, actor_user_id=hold.actor_user_id,
        client_command_id=hold.client_command_id, reason_code=hold.reason_code, reason_text=hold.reason_text,
        is_open=release is None,
        release=(
            QualityHoldReleaseRead(
                id=release.id, quality_hold_id=release.quality_hold_id, effective_time=release.effective_time,
                recorded_time=release.recorded_time, actor_user_id=release.actor_user_id,
                client_command_id=release.client_command_id, release_reason=release.release_reason,
            )
            if release is not None
            else None
        ),
    )


def get_quality_hold(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID, hold_id: uuid.UUID
) -> QualityHoldRead:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    row = db.execute(
        _hold_detail_query().where(
            QualityHold.id == hold_id, QualityHold.tenant_id == tenant_id, QualityHold.batch_id == batch_id
        )
    ).first()
    if row is None:
        raise QualityHoldNotFoundError(str(hold_id))
    release = db.execute(
        select(QualityHoldRelease).where(QualityHoldRelease.quality_hold_id == hold_id)
    ).scalar_one_or_none()
    return _row_to_hold_read(row, release)


def list_quality_holds(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, batch_id: uuid.UUID
) -> list[QualityHoldRead]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    _get_batch_row(db, tenant_id=tenant_id, farm_id=farm_id, batch_id=batch_id)
    rows = db.execute(
        _hold_detail_query()
        .where(QualityHold.tenant_id == tenant_id, QualityHold.batch_id == batch_id)
        .order_by(QualityHold.effective_time, QualityHold.recorded_time)
    ).all()
    hold_ids = [r[0].id for r in rows]
    releases_by_hold: dict[uuid.UUID, QualityHoldRelease] = {}
    if hold_ids:
        release_rows = db.execute(
            select(QualityHoldRelease).where(QualityHoldRelease.quality_hold_id.in_(hold_ids))
        ).scalars()
        releases_by_hold = {r.quality_hold_id: r for r in release_rows}
    return [_row_to_hold_read(r, releases_by_hold.get(r[0].id)) for r in rows]
