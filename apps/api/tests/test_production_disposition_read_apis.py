"""LEAFY-OPS-001 section 28/30: `list_active_production_plates` and
`get_production_disposition_history` -- the narrow, read-only support for
the Leafy Production operator workspace. Mirrors `test_leafy_production_
transfer_read_apis.py`'s established structure.

BROWSER QA CORRECTION 1: `population_root_batch_carrier_assignment_id` is
deliberately carrier-type-generic (every transplant destination gets one,
Nursery Cultivation Plate and Production Cultivation Plate alike). Both read
functions must narrow to `production_cultivation_plate` lineages only --
`list_active_production_plates` already did via its own carrier_types join;
`get_production_disposition_history` did not, and surfaced Nursery
Cultivation Plate lineages as if they were Leafy Production history. See the
exclusion tests below."""

import uuid
from datetime import timedelta

import pytest

from app.services import production_disposition_service
from tests.test_leafy_production_transfer import _leafy_setup, _nursery_plate_source_scenario, _production_plates
from tests.test_production_disposition import _last_event, _plate_scenario, _record_loss
from tests.test_production_disposition_correction import _correct, _events_for_command

pytestmark = pytest.mark.integration


# =====================================================================
# Active plates
# =====================================================================


def test_active_plates_only_production_cultivation_plate_type(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert any(r["batch_carrier_assignment_id"] == root_id for r in rows)


def test_active_plates_excludes_zero_exhausted_lineage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert not any(r["batch_carrier_assignment_id"] == root_id for r in rows)


def test_active_plates_shows_restored_generation_not_original(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    correct = _correct(db_session, tenant, farm, user, target.id)
    reversal = _events_for_command(db_session, correct.id)[0]

    from sqlalchemy import select as _select

    from app.models.batch_carrier_assignment import BatchCarrierAssignment

    b = db_session.execute(
        _select(BatchCarrierAssignment.id).where(
            BatchCarrierAssignment.opening_production_disposition_reversal_event_id == reversal.id
        )
    ).scalar_one()

    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    row_ids = {r["batch_carrier_assignment_id"] for r in rows}
    assert b in row_ids
    assert root_id not in row_ids
    row = next(r for r in rows if r["batch_carrier_assignment_id"] == b)
    assert row["current_living_population"] == 5
    assert row["population_root_batch_carrier_assignment_id"] == root_id


def test_active_plates_batch_filter(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch1, root1, _t1 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)
    batch2, root2, _t2 = _plate_scenario(db_session, tenant, user, farm, opening_count=50)

    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch1.id
    )
    row_ids = {r["batch_carrier_assignment_id"] for r in rows}
    assert root1 in row_ids
    assert root2 not in row_ids


def test_active_plates_location_context_and_warning(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    row = next(r for r in rows if r["batch_carrier_assignment_id"] == root_id)
    assert row["current_location"] is not None
    assert row["has_location_warning"] is False
    assert " / " in row["current_location"]["ancestry_label"]


def test_active_plates_tenant_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex[:8],
        email=f"other-{uuid.uuid4().hex[:6]}@example.com", display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id
    )
    assert not any(r["batch_carrier_assignment_id"] == root_id for r in rows)


def test_active_plates_farm_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{uuid.uuid4().hex[:6]}",
        name="Second Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id
    )
    assert not any(r["batch_carrier_assignment_id"] == root_id for r in rows)


# =====================================================================
# Disposition history
# =====================================================================


def test_history_active_lineage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=root_id,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["is_active"] is True
    assert row["current_living_population"] == 175
    assert len(row["events"]) == 1


def test_history_remains_accessible_after_release(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=root_id,
    )
    assert len(rows) == 1
    assert rows[0]["is_active"] is False
    assert rows[0]["current_living_population"] == 0

    # Must NOT appear in active-plates.
    active_rows = production_disposition_service.list_active_production_plates(
        db_session, tenant_id=tenant.id, farm_id=farm.id
    )
    assert not any(r["batch_carrier_assignment_id"] == root_id for r in active_rows)


def test_history_a_to_b_shows_full_lineage_and_reversed_status(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    _correct(db_session, tenant, farm, user, target.id)

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=root_id,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["is_active"] is True
    assert row["current_living_population"] == 5
    assert len(row["events"]) == 2
    reduction = next(e for e in row["events"] if e["event_kind"] == "REDUCTION")
    reversal = next(e for e in row["events"] if e["event_kind"] == "REVERSAL")
    assert reduction["is_reversed"] is True
    assert reversal["reverses_event_id"] == reduction["id"]


def test_history_batch_filter(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch1, root1, _t1 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)
    batch2, root2, _t2 = _plate_scenario(db_session, tenant, user, farm, opening_count=50)

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch1.id,
    )
    root_ids = {r["population_root_batch_carrier_assignment_id"] for r in rows}
    assert root1 in root_ids
    assert root2 not in root_ids


def test_history_includes_production_plate_with_no_disposition_yet(db_session, active_context_with_farm) -> None:
    """BROWSER QA CORRECTION 1: history discovery is not gated on any
    ProductionDispositionEvent existing -- a fresh, never-disposed-against
    Production Plate lineage is still a valid, real lineage (root's own
    TransplantDestinationLine) and remains discoverable here."""
    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=root_id,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["is_active"] is True
    assert row["opening_population"] == 180
    assert row["current_living_population"] == 180
    assert row["events"] == []


# =====================================================================
# BROWSER QA CORRECTION 1: Leafy Production history must never surface a
# Nursery Cultivation Plate (or any other non-Production-Plate) lineage --
# `population_root_batch_carrier_assignment_id` is deliberately carrier-
# type-generic, so this narrowing must be explicit at the read-model level,
# mirroring `list_active_production_plates`'s own carrier-type join exactly.
# =====================================================================


def test_history_excludes_nursery_cultivation_plate_lineage(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # A real Nursery Cultivation Plate BCA -- opening_transplant_event_id-
    # opened, self-referencing population_root, the same shape as a
    # Production Plate lineage, but a different Carrier type entirely (the
    # exact defect: NP-QA-1/NP-QA-2 appearing in Leafy Production history).
    s, nursery_plate_aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=180)
    # A real Production Plate lineage on the SAME tenant/farm/batch, so this
    # proves carrier-type narrowing, not merely batch/tenant/farm scoping.
    _batch, production_root_id, _t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=100)

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id,
    )
    root_ids = {r["population_root_batch_carrier_assignment_id"] for r in rows}
    assert nursery_plate_aids[0] not in root_ids
    assert production_root_id in root_ids

    # Also proven when directly requested by id -- never discoverable via
    # the `batch_carrier_assignment_id` filter either.
    direct_rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=nursery_plate_aids[0],
    )
    assert direct_rows == []


def test_history_excludes_seed_tray(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    # Sowing-origin BCAs may never carry a population root at all (DB-
    # enforced by the origin-integrity trigger), so a seed tray is already
    # excluded upstream of the carrier-type join -- proven explicitly here
    # as the ticket's own required regression, not merely inferred.
    s, _nursery_plate_aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=180)
    seed_tray_id = s["source_assignment_ids"][0]

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id,
    )
    root_ids = {r["population_root_batch_carrier_assignment_id"] for r in rows}
    assert seed_tray_id not in root_ids

    direct_rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_carrier_assignment_id=seed_tray_id,
    )
    assert direct_rows == []


def test_history_only_production_cultivation_plate_roots_ever_appear(db_session, active_context_with_farm) -> None:
    """Combined proof: with a Nursery Plate, a seed tray, and a released +
    restored Production Plate lineage all present on the same tenant/farm,
    only the Production Plate lineage is ever returned."""
    tenant, user, _headers, farm = active_context_with_farm
    s, nursery_plate_aids = _nursery_plate_source_scenario(db_session, tenant, user, farm, opening_count=180)
    seed_tray_id = s["source_assignment_ids"][0]
    _batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = _record_loss(db_session, tenant, farm, user, root_id, 5, effective_time=t0 + timedelta(hours=1))
    target = _last_event(db_session, record)
    _correct(db_session, tenant, farm, user, target.id)

    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=farm.id,
    )
    root_ids = {r["population_root_batch_carrier_assignment_id"] for r in rows}
    assert root_ids == {root_id}
    assert nursery_plate_aids[0] not in root_ids
    assert seed_tray_id not in root_ids


# =====================================================================
# Tenant / farm isolation (history)
# =====================================================================


def test_history_tenant_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)

    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{uuid.uuid4().hex[:8]}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=uuid.uuid4().hex[:8],
        email=f"other-{uuid.uuid4().hex[:6]}@example.com", display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{uuid.uuid4().hex[:6]}",
        name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=other_tenant.id, farm_id=other_farm.id,
    )
    assert not any(r["population_root_batch_carrier_assignment_id"] == root_id for r in rows)


def test_history_farm_isolation(db_session, active_context_with_farm) -> None:
    from app.services import farm_service

    tenant, user, _headers, farm = active_context_with_farm
    _batch, root_id, _t = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm2-{uuid.uuid4().hex[:6]}",
        name="Second Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    rows = production_disposition_service.get_production_disposition_history(
        db_session, tenant_id=tenant.id, farm_id=other_farm.id,
    )
    assert not any(r["population_root_batch_carrier_assignment_id"] == root_id for r in rows)
