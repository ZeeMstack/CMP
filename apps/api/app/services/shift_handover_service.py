"""PILOT-OPS-001: Shift Handover -- a small, immutable, insert-only note a
user finishing a shift leaves for the farm. Never clones, closes, or
mutates the Work Items it optionally references; open work stays open
(CLAUDE.md "Shift Handover -- Pilot V1")."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.farm_work_item import FarmWorkItem
from app.models.shift_handover import ShiftHandover, ShiftHandoverItem
from app.services import farm_service
from app.services.audit import append_audit_event
from app.services.errors import (
    FarmNotFoundError,
    FarmWorkItemNotFoundError,
    ShiftHandoverCommandReusedWithDifferentPayloadError,
    ShiftHandoverNotFoundError,
)

MAX_HANDOVER_WORK_ITEMS = 50
DEFAULT_LIST_LIMIT = 20


def _require_active_farm(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID):
    farm = farm_service.get_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    if farm.status != "active":
        raise FarmNotFoundError(str(farm_id))
    return farm


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def create_handover(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    farm_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    client_command_id: uuid.UUID,
    effective_time: datetime,
    note: str,
    work_item_ids: list[uuid.UUID],
) -> ShiftHandover:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)

    def _find_by_command() -> ShiftHandover | None:
        return db.execute(
            select(ShiftHandover).where(
                ShiftHandover.tenant_id == tenant_id, ShiftHandover.client_command_id == client_command_id
            )
        ).scalar_one_or_none()

    unique_item_ids = sorted(set(work_item_ids), key=str)
    fingerprint = _fingerprint(tenant_id, farm_id, actor_user_id, effective_time, note, *unique_item_ids)

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise ShiftHandoverCommandReusedWithDifferentPayloadError(str(client_command_id))

    if unique_item_ids:
        found = set(
            db.execute(
                select(FarmWorkItem.id).where(
                    FarmWorkItem.tenant_id == tenant_id,
                    FarmWorkItem.farm_id == farm_id,
                    FarmWorkItem.id.in_(unique_item_ids),
                )
            ).scalars().all()
        )
        missing = set(unique_item_ids) - found
        if missing:
            raise FarmWorkItemNotFoundError(str(next(iter(missing))))

    handover = ShiftHandover(
        tenant_id=tenant_id, farm_id=farm_id, author_user_id=actor_user_id, effective_time=effective_time,
        note=note, client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(handover)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_shift_handovers_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise ShiftHandoverCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    for work_item_id in unique_item_ids:
        db.add(
            ShiftHandoverItem(
                tenant_id=tenant_id, farm_id=farm_id, handover_id=handover.id, work_item_id=work_item_id
            )
        )
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="shift_handover.created",
        entity_type="shift_handover", entity_id=handover.id,
        event_data={"work_item_ids": [str(i) for i in unique_item_ids]},
    )
    db.commit()
    db.refresh(handover)
    return handover


def get_handover_work_item_ids(db: Session, *, handover_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.execute(
            select(ShiftHandoverItem.work_item_id).where(ShiftHandoverItem.handover_id == handover_id)
        ).scalars().all()
    )


def get_latest_handover(db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID) -> ShiftHandover | None:
    return db.execute(
        select(ShiftHandover)
        .where(ShiftHandover.tenant_id == tenant_id, ShiftHandover.farm_id == farm_id)
        .order_by(ShiftHandover.effective_time.desc(), ShiftHandover.recorded_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_handovers(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, limit: int = DEFAULT_LIST_LIMIT
) -> list[ShiftHandover]:
    _require_active_farm(db, tenant_id=tenant_id, farm_id=farm_id)
    return list(
        db.execute(
            select(ShiftHandover)
            .where(ShiftHandover.tenant_id == tenant_id, ShiftHandover.farm_id == farm_id)
            .order_by(ShiftHandover.effective_time.desc(), ShiftHandover.recorded_at.desc())
            .limit(min(limit, DEFAULT_LIST_LIMIT))
        ).scalars().all()
    )
