"""PILOT-WATER-001A section 12-13: NutrientRecipe identity/versioning and
DRAFT-only recipe components. Lifecycle (`draft -> active -> retired`) and
per-command idempotency mirror `growing_protocol_service`'s own identical
shape exactly (activating a new version auto-retires the previous ACTIVE
one in the same transaction). Components may only be added while the
owning version is DRAFT, enforced here -- never a DB trigger, matching
`growing_protocol_service.add_observation_requirement`'s own precedent.

Recipe components are TARGETS ONLY (rule 13/18) -- nothing in this module
ever touches Store inventory existence."""

import hashlib
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.crop import Crop
from app.models.inventory_item import InventoryItem
from app.models.nutrient_recipe import NutrientRecipe
from app.models.nutrient_recipe_component import NutrientRecipeComponent
from app.models.nutrient_recipe_version import NutrientRecipeVersion
from app.models.production_system import ProductionSystem
from app.models.unit_of_measure import UnitOfMeasure
from app.models.variety import Variety
from app.services.audit import append_audit_event
from app.services.errors import (
    CropNotFoundError,
    DuplicateNutrientRecipeCodeError,
    InventoryItemNotFoundError,
    NutrientRecipeNotFoundError,
    NutrientRecipeVersionCommandReusedWithDifferentPayloadError,
    NutrientRecipeVersionNotDraftError,
    NutrientRecipeVersionNotFoundError,
    ProductionSystemNotFoundError,
    UnitOfMeasureNotFoundError,
    VarietyCropMismatchError,
)


def _fingerprint(*parts: object) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode("utf-8")).hexdigest()


def _constraint_name(exc: IntegrityError) -> str | None:
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _require_uom(db: Session, *, uom_id: uuid.UUID) -> UnitOfMeasure:
    uom = db.execute(select(UnitOfMeasure).where(UnitOfMeasure.id == uom_id)).scalar_one_or_none()
    if uom is None:
        raise UnitOfMeasureNotFoundError(str(uom_id))
    return uom


# --- NutrientRecipe identity -----------------------------------------------------------


def register_recipe(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, code: str, name: str, crop_id: uuid.UUID | None,
    variety_id: uuid.UUID | None, production_system_id: uuid.UUID | None,
) -> NutrientRecipe:
    if crop_id is not None:
        crop = db.execute(select(Crop).where(Crop.id == crop_id, Crop.tenant_id == tenant_id)).scalar_one_or_none()
        if crop is None:
            raise CropNotFoundError(str(crop_id))
    if variety_id is not None:
        if crop_id is None:
            raise VarietyCropMismatchError(str(variety_id))
        variety = db.execute(
            select(Variety).where(
                Variety.id == variety_id, Variety.tenant_id == tenant_id, Variety.crop_id == crop_id
            )
        ).scalar_one_or_none()
        if variety is None:
            raise VarietyCropMismatchError(str(variety_id))
    if production_system_id is not None:
        ps = db.execute(
            select(ProductionSystem).where(
                ProductionSystem.id == production_system_id, ProductionSystem.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if ps is None:
            raise ProductionSystemNotFoundError(str(production_system_id))

    recipe = NutrientRecipe(
        tenant_id=tenant_id, crop_id=crop_id, variety_id=variety_id, production_system_id=production_system_id,
        code=code, name=name, created_by_user_id=actor_user_id,
    )
    db.add(recipe)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateNutrientRecipeCodeError(f"{tenant_id}:{code}") from exc

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe.registered",
        entity_type="nutrient_recipe", entity_id=recipe.id, event_data={"code": code, "name": name},
    )
    db.commit()
    db.refresh(recipe)
    return recipe


def get_recipe(db: Session, *, tenant_id: uuid.UUID, nutrient_recipe_id: uuid.UUID) -> NutrientRecipe:
    recipe = db.execute(
        select(NutrientRecipe).where(NutrientRecipe.id == nutrient_recipe_id, NutrientRecipe.tenant_id == tenant_id)
    ).scalar_one_or_none()
    if recipe is None:
        raise NutrientRecipeNotFoundError(str(nutrient_recipe_id))
    return recipe


def list_recipes(db: Session, *, tenant_id: uuid.UUID) -> list[NutrientRecipe]:
    return list(
        db.execute(select(NutrientRecipe).where(NutrientRecipe.tenant_id == tenant_id).order_by(NutrientRecipe.code))
        .scalars()
    )


# --- NutrientRecipeVersion lifecycle -----------------------------------------------------


def _lock_version(db: Session, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> NutrientRecipeVersion:
    version = db.execute(
        select(NutrientRecipeVersion)
        .where(NutrientRecipeVersion.id == version_id, NutrientRecipeVersion.tenant_id == tenant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if version is None:
        raise NutrientRecipeVersionNotFoundError(str(version_id))
    return version


def create_draft_version(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, nutrient_recipe_id: uuid.UUID,
    client_command_id: uuid.UUID, reason: str, target_ec, target_ph, instructions: str | None,
    effective_date: date | None,
) -> NutrientRecipeVersion:
    recipe = get_recipe(db, tenant_id=tenant_id, nutrient_recipe_id=nutrient_recipe_id)
    fingerprint = _fingerprint(tenant_id, nutrient_recipe_id, reason, target_ec, target_ph, effective_date)

    def _find_by_command():
        return db.execute(
            select(NutrientRecipeVersion).where(
                NutrientRecipeVersion.tenant_id == tenant_id,
                NutrientRecipeVersion.client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.request_fingerprint == fingerprint:
            return existing
        raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    next_number = (
        db.execute(
            select(func.max(NutrientRecipeVersion.version_number)).where(
                NutrientRecipeVersion.nutrient_recipe_id == recipe.id
            )
        ).scalar_one()
        or 0
    ) + 1

    version = NutrientRecipeVersion(
        tenant_id=tenant_id, nutrient_recipe_id=recipe.id, version_number=next_number, state="draft",
        author_user_id=actor_user_id, reason=reason, target_ec=target_ec, target_ph=target_ph,
        instructions=instructions, effective_date=effective_date, client_command_id=client_command_id,
        request_fingerprint=fingerprint,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_nutrient_recipe_versions_tenant_client_command_id":
            replay = _find_by_command()
            if replay is not None and replay.request_fingerprint == fingerprint:
                return replay
            raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe_version.created",
        entity_type="nutrient_recipe_version", entity_id=version.id,
        event_data={"nutrient_recipe_id": str(nutrient_recipe_id), "version_number": version.version_number},
    )
    db.commit()
    db.refresh(version)
    return version


def get_version(db: Session, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> NutrientRecipeVersion:
    version = db.execute(
        select(NutrientRecipeVersion).where(
            NutrientRecipeVersion.id == version_id, NutrientRecipeVersion.tenant_id == tenant_id
        )
    ).scalar_one_or_none()
    if version is None:
        raise NutrientRecipeVersionNotFoundError(str(version_id))
    return version


def list_versions(db: Session, *, tenant_id: uuid.UUID, nutrient_recipe_id: uuid.UUID) -> list[NutrientRecipeVersion]:
    return list(
        db.execute(
            select(NutrientRecipeVersion)
            .where(
                NutrientRecipeVersion.tenant_id == tenant_id,
                NutrientRecipeVersion.nutrient_recipe_id == nutrient_recipe_id,
            )
            .order_by(NutrientRecipeVersion.version_number)
        ).scalars()
    )


def activate_version(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, version_id: uuid.UUID, client_command_id: uuid.UUID,
) -> NutrientRecipeVersion:
    fingerprint = _fingerprint(tenant_id, version_id, "activate")

    def _find_by_command():
        return db.execute(
            select(NutrientRecipeVersion).where(
                NutrientRecipeVersion.tenant_id == tenant_id,
                NutrientRecipeVersion.activation_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.activation_request_fingerprint == fingerprint:
            return existing
        raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    version = _lock_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.state != "draft":
        raise NutrientRecipeVersionNotDraftError(str(version_id))

    now = datetime.now(timezone.utc)
    previous_active = db.execute(
        select(NutrientRecipeVersion)
        .where(
            NutrientRecipeVersion.nutrient_recipe_id == version.nutrient_recipe_id,
            NutrientRecipeVersion.state == "active",
        )
        .with_for_update()
    ).scalar_one_or_none()

    replaced_version_id = None
    if previous_active is not None:
        previous_active.state = "retired"
        previous_active.retired_at = now
        replaced_version_id = previous_active.id
        db.flush()

    version.state = "active"
    version.activated_at = now
    version.activation_client_command_id = client_command_id
    version.activation_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_nutrient_recipe_versions_tenant_activation_command":
            replay = _find_by_command()
            if replay is not None and replay.activation_request_fingerprint == fingerprint:
                return replay
            raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    if previous_active is not None:
        append_audit_event(
            db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe_version.retired",
            entity_type="nutrient_recipe_version", entity_id=previous_active.id,
            event_data={"reason": "superseded", "superseded_by_version_id": str(version.id)},
        )
    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe_version.activated",
        entity_type="nutrient_recipe_version", entity_id=version.id,
        event_data={"version_number": version.version_number, "replaced_version_id": str(replaced_version_id) if replaced_version_id else None},
    )
    db.commit()
    db.refresh(version)
    return version


def retire_version(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, version_id: uuid.UUID, client_command_id: uuid.UUID,
) -> NutrientRecipeVersion:
    fingerprint = _fingerprint(tenant_id, version_id, "retire")

    def _find_by_command():
        return db.execute(
            select(NutrientRecipeVersion).where(
                NutrientRecipeVersion.tenant_id == tenant_id,
                NutrientRecipeVersion.retirement_client_command_id == client_command_id,
            )
        ).scalar_one_or_none()

    existing = _find_by_command()
    if existing is not None:
        if existing.retirement_request_fingerprint == fingerprint:
            return existing
        raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id))

    version = _lock_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.state != "active":
        raise NutrientRecipeVersionNotDraftError(str(version_id))

    version.state = "retired"
    version.retired_at = datetime.now(timezone.utc)
    version.retirement_client_command_id = client_command_id
    version.retirement_request_fingerprint = fingerprint
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if _constraint_name(exc) == "ux_nutrient_recipe_versions_tenant_retirement_command":
            replay = _find_by_command()
            if replay is not None and replay.retirement_request_fingerprint == fingerprint:
                return replay
            raise NutrientRecipeVersionCommandReusedWithDifferentPayloadError(str(client_command_id)) from exc
        raise

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe_version.retired",
        entity_type="nutrient_recipe_version", entity_id=version.id, event_data={"reason": "explicit"},
    )
    db.commit()
    db.refresh(version)
    return version


# --- NutrientRecipeComponent (DRAFT-only) ------------------------------------------------


def add_component(
    db: Session, *, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, version_id: uuid.UUID,
    inventory_item_id: uuid.UUID | None, component_label: str, target_quantity, target_quantity_uom_id: uuid.UUID,
    basis_volume, basis_volume_uom_id: uuid.UUID | None, sequence_number: int | None, instructions: str | None,
) -> NutrientRecipeComponent:
    version = get_version(db, tenant_id=tenant_id, version_id=version_id)
    if version.state != "draft":
        raise NutrientRecipeVersionNotDraftError(str(version_id))

    _require_uom(db, uom_id=target_quantity_uom_id)
    if basis_volume_uom_id is not None:
        _require_uom(db, uom_id=basis_volume_uom_id)
    if inventory_item_id is not None:
        item = db.execute(
            select(InventoryItem).where(
                InventoryItem.id == inventory_item_id, InventoryItem.tenant_id == tenant_id
            )
        ).scalar_one_or_none()
        if item is None:
            raise InventoryItemNotFoundError(str(inventory_item_id))

    component = NutrientRecipeComponent(
        tenant_id=tenant_id, nutrient_recipe_version_id=version.id, inventory_item_id=inventory_item_id,
        component_label=component_label, target_quantity=target_quantity,
        target_quantity_uom_id=target_quantity_uom_id, basis_volume=basis_volume,
        basis_volume_uom_id=basis_volume_uom_id, sequence_number=sequence_number, instructions=instructions,
    )
    db.add(component)
    db.flush()

    append_audit_event(
        db, tenant_id=tenant_id, actor_user_id=actor_user_id, action="nutrient_recipe_component.added",
        entity_type="nutrient_recipe_component", entity_id=component.id,
        event_data={"nutrient_recipe_version_id": str(version_id), "component_label": component_label},
    )
    db.commit()
    db.refresh(component)
    return component


def list_components(db: Session, *, tenant_id: uuid.UUID, version_id: uuid.UUID) -> list[NutrientRecipeComponent]:
    get_version(db, tenant_id=tenant_id, version_id=version_id)
    return list(
        db.execute(
            select(NutrientRecipeComponent)
            .where(
                NutrientRecipeComponent.tenant_id == tenant_id,
                NutrientRecipeComponent.nutrient_recipe_version_id == version_id,
            )
            .order_by(NutrientRecipeComponent.sequence_number.nullslast())
        ).scalars()
    )
