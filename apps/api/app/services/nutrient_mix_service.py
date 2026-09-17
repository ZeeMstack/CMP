"""PILOT-WATER-001A section 14-15: NutrientMix (what was ACTUALLY prepared)
and NutrientMixInput (actual ingredient facts). `nutrient_recipe_version_id`
is optional reference/guidance only -- creating a Mix never copies the
recipe's target quantities as actual inputs (rule 3/section 14); the caller
supplies every actual input explicitly. Recording a `NutrientMixInput`
NEVER touches Store inventory existence (section 15) -- this module never
imports or references `inventory_existence_ledger_service`/
`inventory_material_event_service`."""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.inventory_item import InventoryItem
from app.models.nutrient_mix import NutrientMix
from app.models.nutrient_mix_input import NutrientMixInput
from app.models.unit_of_measure import UnitOfMeasure
from app.services import water_topology_service
from app.services.audit import append_audit_event
from app.services.errors import (
    InventoryItemNotFoundError,
    NutrientMixNotFoundError,
    NutrientMixValidationError,
    UnitOfMeasureKindMismatchError,
    UnitOfMeasureNotFoundError,
)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_volume_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    if uom.quantity_kind != "volume":
        raise UnitOfMeasureKindMismatchError(f"{uom.code} is not a volume unit")
    return uom


def _require_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    return uom


def record_mix(
    db: Session, *, tenant_id: uuid.UUID, farm_id: uuid.UUID, actor_user_id: uuid.UUID, reservoir_id: uuid.UUID,
    nutrient_recipe_version_id: uuid.UUID | None, effective_at: datetime, target_volume, target_volume_uom_id,
    actual_volume, actual_volume_uom_id, notes: str | None, client_command_id: uuid.UUID,
    inputs: list[dict],
) -> NutrientMix:
    """`inputs`: a list of dicts with keys `inventory_item_id` (optional),
    `component_label`, `actual_quantity`, `actual_quantity_uom_id`,
    `sequence_number` (optional), `note` (optional) -- recorded atomically
    with the Mix header in the same transaction, never a separate command,
    since a Mix with zero recorded inputs is not a useful fact."""
    water_topology_service.get_reservoir(db, tenant_id=tenant_id, reservoir_id=reservoir_id)
    if target_volume_uom_id is not None:
        _require_volume_uom(db, uom_id=target_volume_uom_id)
    if actual_volume_uom_id is not None:
        _require_volume_uom(db, uom_id=actual_volume_uom_id)
    if not inputs:
        raise NutrientMixValidationError("a NutrientMix must record at least one actual input")

    fingerprint = _fingerprint(
        tenant_id, reservoir_id, nutrient_recipe_version_id, effective_at, target_volume, actual_volume,
        tuple((i.get("inventory_item_id"), i["component_label"], i["actual_quantity"]) for i in inputs),
    )
    existing = db.execute(
        select(NutrientMix).where(NutrientMix.tenant_id == tenant_id, NutrientMix.client_command_id == client_command_id)
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise NutrientMixValidationError(f"client_command_id {client_command_id} reused with a different payload")

    mix = NutrientMix(
        tenant_id=tenant_id, farm_id=farm_id, reservoir_id=reservoir_id,
        nutrient_recipe_version_id=nutrient_recipe_version_id, prepared_by_user_id=actor_user_id,
        effective_at=effective_at, target_volume=target_volume, target_volume_uom_id=target_volume_uom_id,
        actual_volume=actual_volume, actual_volume_uom_id=actual_volume_uom_id, notes=notes,
        client_command_id=client_command_id, request_fingerprint=fingerprint,
    )
    db.add(mix)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_nutrient_mixes_tenant_client_command_id":
            replay = db.execute(
                select(NutrientMix).where(
                    NutrientMix.tenant_id == tenant_id, NutrientMix.client_command_id == client_command_id
                )
            ).scalar_one_or_none()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
        raise

    for entry in inputs:
        inventory_item_id = entry.get("inventory_item_id")
        if inventory_item_id is not None:
            item = db.execute(
                select(InventoryItem).where(InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id)
            ).scalar_one_or_none()
            if item is None:
                raise InventoryItemNotFoundError(str(inventory_item_id))
        _require_uom(db, uom_id=entry["actual_quantity_uom_id"])
        mix_input = NutrientMixInput(
            tenant_id=tenant_id, farm_id=farm_id, nutrient_mix_id=mix.id, inventory_item_id=inventory_item_id,
            component_label=entry["component_label"], actual_quantity=entry["actual_quantity"],
            actual_quantity_uom_id=entry["actual_quantity_uom_id"], sequence_number=entry.get("sequence_number"),
            note=entry.get("note"),
        )
        db.add(mix_input)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_mix.recorded",
        entity_type="nutrient_mix", entity_id=mix.id,
        event_data={
            "reservoir_id": str(reservoir_id),
            "nutrient_recipe_version_id": str(nutrient_recipe_version_id) if nutrient_recipe_version_id else None,
            "input_count": len(inputs),
        },
    )
    db.commit()
    db.refresh(mix)
    return mix


def get_mix(db: Session, *, tenant_id: uuid.UUID, nutrient_mix_id: uuid.UUID) -> NutrientMix:
    mix = db.execute(
        select(NutrientMix).where(NutrientMix.id == nutrient_mix_id, NutrientMix.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if mix is None:
        raise NutrientMixNotFoundError(str(nutrient_mix_id))
    return mix


def list_mix_inputs(db: Session, *, tenant_id: uuid.UUID, nutrient_mix_id: uuid.UUID) -> list[NutrientMixInput]:
    get_mix(db, tenant_id=tenant_id, nutrient_mix_id=nutrient_mix_id)
    return list(
        db.execute(
            select(NutrientMixInput)
            .where(NutrientMixInput.tenant_id == tenant_id, NutrientMixInput.nutrient_mix_id == nutrient_mix_id)
            .order_by(NutrientMixInput.sequence_number.nullslast())
        ).scalars()
    )


def list_mixes_for_reservoir(db: Session, *, tenant_id: uuid.UUID, reservoir_id: uuid.UUID) -> list[NutrientMix]:
    return list(
        db.execute(
            select(NutrientMix)
            .where(NutrientMix.tenant_id == tenant_id, NutrientMix.reservoir_id == reservoir_id)
            .order_by(NutrientMix.effective_at.desc())
        ).scalars()
    )
