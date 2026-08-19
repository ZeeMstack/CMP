"""CARRIER-CONFIG-001: CarrierType (platform role) -> CarrierSpecification
(tenant-configurable reusable physical design) -> Carrier (individually
traceable physical object). Physical equipment configuration only --
deliberately independent of SowingEventLine.sown_site_count/seed_count and
of TransplantDestinationLine.assigned_plant_count (this ticket adds no
constraint linking any of them)."""
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.main import app
from app.models.audit_event import AuditEvent
from app.models.carrier_type import CarrierType
from app.schemas.carrier_specification import CarrierSpecificationCreate
from app.services import carrier_service, carrier_specification_service, farm_service, tenant_service
from app.services.errors import (
    CarrierSpecificationInactiveError,
    CarrierSpecificationNotFoundError,
    CarrierSpecificationRequiredError,
    CarrierSpecificationStructurallyLockedError,
    CarrierSpecificationTypeMismatchError,
    CarrierSpecificationValidationError,
    CarrierTypeNotFoundError,
    DuplicateCarrierSpecificationCodeError,
)

# --- Application-level (Pydantic) validation — no DB required -----------------------


def test_specification_code_trimmed_and_uppercased() -> None:
    payload = CarrierSpecificationCreate(carrier_type_code="seed_tray", code="  st-200  ", name="200 Cell Tray")
    assert payload.code == "ST-200"


def test_specification_blank_name_rejected() -> None:
    with pytest.raises(ValueError):
        CarrierSpecificationCreate(carrier_type_code="seed_tray", code="ST-200", name="   ")


def test_specification_negative_length_rejected() -> None:
    with pytest.raises(ValueError):
        CarrierSpecificationCreate(carrier_type_code="seed_tray", code="ST-200", name="X", length_mm=-1)


def test_specification_zero_biological_position_count_rejected() -> None:
    with pytest.raises(ValueError):
        CarrierSpecificationCreate(
            carrier_type_code="seed_tray", code="ST-200", name="X", biological_position_count=0
        )


def test_specification_service_exposes_no_delete_function() -> None:
    assert not hasattr(carrier_specification_service, "delete_carrier_specification")


def test_no_delete_route_registered_for_carrier_specifications() -> None:
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "DELETE" in methods and "carrier-specification" in path:
            pytest.fail(f"unexpected DELETE route: {path}")


# --- Seeded platform metadata --------------------------------------------------------


@pytest.mark.integration
def test_new_role_specific_plate_types_seeded(db_session) -> None:
    rows = {
        t.code: t
        for t in db_session.execute(
            select(CarrierType).where(
                CarrierType.code.in_(["nursery_cultivation_plate", "production_cultivation_plate"])
            )
        ).scalars()
    }
    assert set(rows) == {"nursery_cultivation_plate", "production_cultivation_plate"}
    for carrier_type in rows.values():
        assert carrier_type.requires_specification is True
        assert carrier_type.biological_position_label == "Holes"


@pytest.mark.integration
def test_legacy_cultivation_plate_preserved(db_session) -> None:
    legacy = db_session.execute(select(CarrierType).where(CarrierType.code == "cultivation_plate")).scalar_one()
    assert legacy.requires_specification is False
    assert legacy.biological_position_label is None


@pytest.mark.integration
def test_other_legacy_types_unaffected(db_session) -> None:
    for code in ("grow_cube", "grow_bag", "harvest_crate"):
        row = db_session.execute(select(CarrierType).where(CarrierType.code == code)).scalar_one()
        assert row.requires_specification is False
        assert row.biological_position_label is None


@pytest.mark.integration
def test_seed_tray_label_seeded_and_now_required(db_session) -> None:
    """CARRIER-CONFIG-001 seeded `biological_position_label='Cells'` for
    seed_tray but deliberately deferred flipping `requires_specification`
    to a dedicated follow-up (see that ticket's final report), so it would
    not also have to rewrite the dozens of pre-existing, unrelated-domain
    test scenario helpers that register seed_tray carriers as incidental
    setup. CARRIER-CONFIG-001A is that follow-up: it flips the flag to
    True (migration d9a417c5e832) once every one of those helpers was
    updated to supply a specification_id."""
    seed_tray = db_session.execute(select(CarrierType).where(CarrierType.code == "seed_tray")).scalar_one()
    assert seed_tray.biological_position_label == "Cells"
    assert seed_tray.requires_specification is True


# --- Specification create/read ------------------------------------------------------


def _register_spec(db_session, tenant, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
        code="NCP-150", name="150 Hole Nursery Plate", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=150,
    )
    defaults.update(overrides)
    return carrier_specification_service.register_carrier_specification(db_session, **defaults)


@pytest.mark.integration
def test_specification_create(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    assert spec.code == "NCP-150"
    assert spec.carrier_type_code == "nursery_cultivation_plate"
    assert spec.biological_position_label == "Holes"
    assert spec.status == "active"
    assert spec.is_structurally_locked is False
    assert spec.length_mm == 300 and spec.width_mm == 200 and spec.height_mm == 50
    assert spec.biological_position_count == 150


@pytest.mark.integration
def test_specification_unknown_carrier_type_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierTypeNotFoundError):
        carrier_specification_service.register_carrier_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="not_a_type",
            code="X", name="X", length_mm=None, width_mm=None, height_mm=None, biological_position_count=None,
        )


@pytest.mark.integration
def test_specification_tenant_isolation(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    other_tenant = tenant_service.create_tenant(db_session, code="other-spec-tenant", name="Other")
    with pytest.raises(CarrierSpecificationNotFoundError):
        carrier_specification_service.get_carrier_specification(
            db_session, tenant_id=other_tenant.id, specification_id=spec.id
        )


@pytest.mark.integration
def test_specification_case_insensitive_code_uniqueness(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _register_spec(db_session, tenant, user, code="NCP-150")
    with pytest.raises(DuplicateCarrierSpecificationCodeError):
        _register_spec(db_session, tenant, user, code="ncp-150")


@pytest.mark.integration
def test_specification_same_code_allowed_different_tenants(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec_a = _register_spec(db_session, tenant, user, code="NCP-150")
    other_tenant = tenant_service.create_tenant(db_session, code="other-spec-code", name="Other")
    spec_b = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, carrier_type_code="nursery_cultivation_plate",
        code="NCP-150", name="Other design", length_mm=1, width_mm=1, height_mm=None,
        biological_position_count=1,
    )
    assert spec_a.code == spec_b.code
    assert spec_a.tenant_id != spec_b.tenant_id


@pytest.mark.integration
def test_specification_missing_required_dimensions_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierSpecificationValidationError):
        carrier_specification_service.register_carrier_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="nursery_cultivation_plate",
            code="NCP-X", name="X", length_mm=None, width_mm=200, height_mm=None,
            biological_position_count=150,
        )


@pytest.mark.integration
def test_new_seed_tray_specification_missing_biological_position_count_rejected(
    db_session, active_context_with_farm
) -> None:
    """CARRIER-CONFIG-001B section 5: from this ticket onward, a NEW
    seed_tray CarrierSpecification must carry a positive
    biological_position_count. seed_tray already requires_specification=
    true (CARRIER-CONFIG-001A), so this is enforced by the SAME generic
    `_require_minimum_fields_if_specification_required` rule that
    `test_specification_missing_required_dimensions_rejected` above already
    proves for nursery_cultivation_plate -- this test proves it holds for
    seed_tray specifically, with no new production code required."""
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierSpecificationValidationError):
        carrier_specification_service.register_carrier_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
            code=f"ST-NOCAP-{uuid.uuid4().hex[:8]}", name="X", length_mm=300, width_mm=200, height_mm=None,
            biological_position_count=None,
        )


@pytest.mark.integration
def test_new_seed_tray_specification_with_positive_biological_position_count_succeeds(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-CAP-{uuid.uuid4().hex[:8]}", name="200 Cell Tray", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=200,
    )
    assert spec.biological_position_count == 200


@pytest.mark.integration
def test_unreferenced_seed_tray_specification_update_to_null_biological_position_count_rejected(
    db_session, active_context_with_farm
) -> None:
    """CARRIER-CONFIG-001B pre-commit audit follow-up: an UPDATE, not just
    CREATE, must re-enforce the seed_tray minimum-field invariant. The
    specification stays unreferenced by any Carrier so this exercises
    `_require_minimum_fields_if_specification_required` specifically, not
    `CarrierSpecificationStructurallyLockedError` (see
    test_structural_edit_after_first_carrier_rejected_service above for
    that separate rule)."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-NULLIFY-{uuid.uuid4().hex[:8]}", name="200 Cell Tray", length_mm=300, width_mm=200, height_mm=50,
        biological_position_count=200,
    )
    with pytest.raises(CarrierSpecificationValidationError):
        carrier_specification_service.update_carrier_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id,
            carrier_type_code="seed_tray", code=spec.code, name=spec.name,
            length_mm=spec.length_mm, width_mm=spec.width_mm, height_mm=spec.height_mm,
            biological_position_count=None,
        )
    unchanged = carrier_specification_service.get_carrier_specification(
        db_session, tenant_id=tenant.id, specification_id=spec.id
    )
    assert unchanged.biological_position_count == 200


@pytest.mark.integration
def test_specification_optional_type_allows_fully_unset_dimensions(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="grow_bag",
        code="GB-X", name="Generic Grow Bag", length_mm=None, width_mm=None, height_mm=None,
        biological_position_count=None,
    )
    assert spec.length_mm is None
    assert spec.biological_position_count is None


@pytest.mark.integration
def test_list_carrier_specifications_filters(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec_a = _register_spec(db_session, tenant, user, code="NCP-A")
    spec_b = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="production_cultivation_plate",
        code="PCP-A", name="48 Hole Production Plate", length_mm=1, width_mm=1, height_mm=None,
        biological_position_count=48,
    )
    all_specs = carrier_specification_service.list_carrier_specifications(
        db_session, tenant_id=tenant.id, carrier_type_code=None, status=None
    )
    assert {s.id for s in all_specs} == {spec_a.id, spec_b.id}

    nursery_only = carrier_specification_service.list_carrier_specifications(
        db_session, tenant_id=tenant.id, carrier_type_code="nursery_cultivation_plate", status=None
    )
    assert {s.id for s in nursery_only} == {spec_a.id}

    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec_b.id
    )
    active_only = carrier_specification_service.list_carrier_specifications(
        db_session, tenant_id=tenant.id, carrier_type_code=None, status="active"
    )
    assert {s.id for s in active_only} == {spec_a.id}


# --- Carrier registration with specification -----------------------------------------


@pytest.mark.integration
def test_carrier_registration_with_specification_derives_type(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-00001", issued_date=None,
    )
    carrier_type = db_session.get(CarrierType, carrier.carrier_type_id)
    assert carrier_type.code == "nursery_cultivation_plate"
    assert carrier.specification_id == spec.id


@pytest.mark.integration
def test_carrier_registration_both_supplied_matching_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="nursery_cultivation_plate", specification_id=spec.id, code="NCP-00002",
        issued_date=None,
    )
    assert carrier.specification_id == spec.id


@pytest.mark.integration
def test_carrier_registration_type_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)  # nursery_cultivation_plate
    with pytest.raises(CarrierSpecificationTypeMismatchError):
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="production_cultivation_plate", specification_id=spec.id, code="X",
            issued_date=None,
        )


@pytest.mark.integration
def test_carrier_registration_cross_tenant_specification_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    other_tenant = tenant_service.create_tenant(db_session, code="other-carrier-spec-tenant", name="Other")
    other_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, carrier_type_code="nursery_cultivation_plate",
        code="X", name="X", length_mm=1, width_mm=1, height_mm=None, biological_position_count=1,
    )
    with pytest.raises(CarrierSpecificationNotFoundError):
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=other_spec.id, code="X", issued_date=None,
        )


@pytest.mark.integration
def test_specification_required_type_rejects_missing_spec(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierSpecificationRequiredError):
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="nursery_cultivation_plate", code="X", issued_date=None,
        )


@pytest.mark.integration
def test_specification_required_type_rejects_neither_supplied(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(CarrierSpecificationRequiredError):
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            code="X", issued_date=None,
        )


@pytest.mark.integration
def test_legacy_non_required_type_registration_still_works_without_spec(
    db_session, active_context_with_farm
) -> None:
    # CARRIER-CONFIG-001A flipped seed_tray.requires_specification to true,
    # so seed_tray is no longer a valid example of a non-required type here
    # -- grow_bag (untouched by either ticket) now illustrates the same
    # general rule this test's name/purpose is actually about: a CarrierType
    # that does NOT require a specification still registers fine without one.
    tenant, user, _headers, farm = active_context_with_farm
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        carrier_type_code="grow_bag", code="GB-LEGACY", issued_date=None,
    )
    assert carrier.specification_id is None


@pytest.mark.integration
def test_inactive_specification_rejected_for_new_carrier(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    with pytest.raises(CarrierSpecificationInactiveError):
        carrier_service.register_carrier(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=spec.id, code="X", issued_date=None,
        )


@pytest.mark.integration
def test_existing_carrier_referencing_deactivated_specification_remains_valid(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-EARLY", issued_date=None,
    )
    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    fetched = carrier_service.get_carrier(db_session, tenant_id=tenant.id, farm_id=farm.id, carrier_id=carrier.id)
    assert fetched.specification_id == spec.id


@pytest.mark.integration
def test_reactivate_specification_allows_new_registration_again(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    reactivated = carrier_specification_service.reactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    assert reactivated.status == "active"
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-AFTER-REACT", issued_date=None,
    )
    assert carrier.specification_id == spec.id


@pytest.mark.integration
def test_bulk_register_carriers_with_specification(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    created = carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code_prefix="NCP-BULK-", start=1, end=5, pad_width=3,
    )
    assert len(created) == 5
    assert all(c.specification_id == spec.id for c in created)
    assert all(c.carrier_type_id == db_session.get(CarrierType, spec.carrier_type_id).id for c in created)


@pytest.mark.integration
def test_bulk_register_carriers_type_mismatch_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)  # nursery_cultivation_plate
    with pytest.raises(CarrierSpecificationTypeMismatchError):
        carrier_service.bulk_register_carriers(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            carrier_type_code="production_cultivation_plate", specification_id=spec.id,
            code_prefix="X-", start=1, end=2, pad_width=2,
        )


@pytest.mark.integration
def test_bulk_register_carriers_cross_tenant_specification_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    other_tenant = tenant_service.create_tenant(db_session, code="other-bulk-spec-tenant", name="Other")
    other_spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=other_tenant.id, actor_user_id=None, carrier_type_code="nursery_cultivation_plate",
        code="X", name="X", length_mm=1, width_mm=1, height_mm=None, biological_position_count=1,
    )
    with pytest.raises(CarrierSpecificationNotFoundError):
        carrier_service.bulk_register_carriers(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            specification_id=other_spec.id, code_prefix="X-", start=1, end=2, pad_width=2,
        )


# --- Structural mutability ------------------------------------------------------------


@pytest.mark.integration
def test_structural_edit_before_first_carrier_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    updated = carrier_specification_service.update_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id,
        carrier_type_code="nursery_cultivation_plate", code="NCP-150B", name=spec.name,
        length_mm=310, width_mm=200, height_mm=50, biological_position_count=150,
    )
    assert updated.code == "NCP-150B"
    assert updated.length_mm == 310
    assert updated.is_structurally_locked is False


@pytest.mark.integration
def test_structural_edit_after_first_carrier_rejected_service(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-LOCKED", issued_date=None,
    )
    with pytest.raises(CarrierSpecificationStructurallyLockedError):
        carrier_specification_service.update_carrier_specification(
            db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id,
            carrier_type_code="nursery_cultivation_plate", code=spec.code, name=spec.name,
            length_mm=999, width_mm=spec.width_mm, height_mm=spec.height_mm,
            biological_position_count=spec.biological_position_count,
        )


@pytest.mark.integration
def test_non_structural_resubmission_after_first_carrier_succeeds(db_session, active_context_with_farm) -> None:
    """Submitting the SAME structural values back (no actual change) must
    not be rejected -- only a genuine structural DIFFERENCE is locked."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-UNCHANGED", issued_date=None,
    )
    updated = carrier_specification_service.update_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id,
        carrier_type_code="nursery_cultivation_plate", code=spec.code, name="Renamed Only",
        length_mm=spec.length_mm, width_mm=spec.width_mm, height_mm=spec.height_mm,
        biological_position_count=spec.biological_position_count,
    )
    assert updated.name == "Renamed Only"
    assert updated.length_mm == spec.length_mm


@pytest.mark.integration
def test_structural_edit_after_first_carrier_rejected_direct_sql(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-LOCKED-2", issued_date=None,
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE carrier_specifications SET biological_position_count = 999 WHERE id = :id"),
                {"id": spec.id},
            )


@pytest.mark.integration
def test_name_edit_after_use_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="NCP-NAME", issued_date=None,
    )
    updated = carrier_specification_service.update_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id,
        carrier_type_code="nursery_cultivation_plate", code=spec.code, name="Renamed Design",
        length_mm=spec.length_mm, width_mm=spec.width_mm, height_mm=spec.height_mm,
        biological_position_count=spec.biological_position_count,
    )
    assert updated.name == "Renamed Design"
    assert updated.is_structurally_locked is True


# --- Deactivate/reactivate -------------------------------------------------------------


@pytest.mark.integration
def test_deactivate_succeeds(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    result = carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    assert result.status == "inactive"


# --- Audit --------------------------------------------------------------------------


@pytest.mark.integration
def test_audit_events_emitted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = _register_spec(db_session, tenant, user)
    carrier_specification_service.deactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    carrier_specification_service.reactivate_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, specification_id=spec.id
    )
    for action in (
        "carrier_specification.registered", "carrier_specification.deactivated",
        "carrier_specification.reactivated",
    ):
        count = db_session.execute(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == action, AuditEvent.entity_id == spec.id
            )
        ).scalar_one()
        assert count == 1, action


# --- Authorization --------------------------------------------------------------------


@pytest.fixture
def _dev_auth_enabled(monkeypatch):
    """Local to this file only -- tests/conftest.py's shared `client` fixture
    stays untouched; the non-hermetic dev-auth test harness it and 35 other
    established files depend on (ambient ENABLE_DEV_AUTH from the developer's
    own .env) is a separate, pre-existing test-infrastructure issue, out of
    scope here. Forces `settings.enable_dev_auth` on for exactly the duration
    of a test that needs to exercise the dev-header HTTP auth path, so that
    assertion doesn't depend on the ambient .env value -- mirrors the same
    monkeypatch technique test_dev_auth.py already uses for the negative
    case. Does not touch the .env file or the Settings class default."""
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


@pytest.mark.integration
def test_operator_role_cannot_manage_carrier_specifications(
    client, db_session, active_context_with_farm, _dev_auth_enabled
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import membership_service, user_service

    operator_user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="spec-operator", email="spec-op@example.com",
        display_name="Operator",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=operator_user.id, role_code="operator", actor_user_id=None
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(operator_user.id)}
    response = client.post(
        "/carrier-specifications", headers=headers,
        json={"carrier_type_code": "nursery_cultivation_plate", "code": "OP-X", "name": "X"},
    )
    assert response.status_code == 403


@pytest.mark.integration
def test_farm_manager_role_can_manage_carrier_specifications(
    client, db_session, active_context_with_farm, _dev_auth_enabled
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import membership_service, user_service

    manager_user = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject="spec-manager", email="spec-mgr@example.com",
        display_name="Manager",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=manager_user.id, role_code="farm_manager", actor_user_id=None
    )
    db_session.commit()
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(manager_user.id)}
    response = client.post(
        "/carrier-specifications", headers=headers,
        json={
            "carrier_type_code": "nursery_cultivation_plate", "code": "MGR-X", "name": "X",
            "length_mm": 100, "width_mm": 100, "biological_position_count": 10,
        },
    )
    assert response.status_code == 201, response.text


# --- Physical vs operational quantity independence (sections 12/13/36-38) ------------


@pytest.mark.integration
def test_seed_tray_specification_independent_from_sown_site_count_and_seed_count(
    db_session, active_context_with_farm
) -> None:
    """A seed_tray specification's biological_position_count is never read
    or constrained by SowingEventLine -- sown_site_count/seed_count are
    completely independent operational facts, including a seed_count that
    exceeds the physical cell count (multiple seeds per site)."""
    from app.services import crop_batch_service, crop_service, production_system_service, sowing_service, workflow_service

    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    spec = carrier_specification_service.register_carrier_specification(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, carrier_type_code="seed_tray",
        code=f"ST-IND-{suffix}", name="200 Cell Tray", length_mm=500, width_mm=300, height_mm=50,
        biological_position_count=200,
    )
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code=f"ST-IND-{suffix}-001", issued_date=None,
    )

    crop = crop_service.register_crop(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"CROP-{suffix}",
        common_name="Test Crop", scientific_name=None, crop_category="leafy_green",
    )
    variety = crop_service.register_variety(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, code=f"VAR-{suffix}",
        name="Test Variety", supplier_reference=None,
    )
    ps = production_system_service.register_production_system(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"PS-{suffix}", name="Test System",
        description=None,
    )
    workflow = workflow_service.register_workflow(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, crop_id=crop.id, variety_id=variety.id,
        production_system_id=ps.id, code=f"WF-{suffix}", name="Test Workflow",
    )
    version = workflow_service.create_draft_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id
    )
    seeding = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="SEEDING", name="Seeding", display_order=0, stage_category="seeding",
        expected_duration_minutes=None, permitted_location_type_code=None,
        required_carrier_type_code="seed_tray", is_start=True, is_terminal=False,
    )
    complete = workflow_service.add_stage(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        code="COMPLETE", name="Complete", display_order=1, stage_category="completed",
        expected_duration_minutes=None, permitted_location_type_code=None, required_carrier_type_code=None,
        is_start=False, is_terminal=True,
    )
    workflow_service.add_transition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id,
        from_stage_id=seeding.id, to_stage_id=complete.id, code="ADVANCE-1", name="Advance 1",
    )
    workflow_service.publish_version(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, workflow_id=workflow.id, version_id=version.id
    )
    from datetime import datetime, timezone

    batch = crop_batch_service.create_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        code=f"BATCH-{suffix}", workflow_id=workflow.id, effective_time=datetime.now(timezone.utc),
    )
    seed_lot = sowing_service.register_seed_lot(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, crop_id=crop.id,
        variety_id=variety.id, code=f"LOT-{suffix}", supplier_name=None, supplier_lot_reference=None,
        received_date=None, expiry_date=None,
    )

    # sown_site_count (180) and seed_count (400, > 200 physical cells --
    # multiple seeds per site) are both accepted -- neither is read against
    # the specification's biological_position_count anywhere.
    event = sowing_service.sow_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=batch.id,
        client_command_id=uuid.uuid4(), effective_time=datetime.now(timezone.utc), note=None,
        lines=[
            {
                "carrier_id": carrier.id, "seed_lot_id": seed_lot.id, "sown_site_count": 180,
                "seed_count": 400, "line_note": None,
            }
        ],
    )
    assert event is not None
