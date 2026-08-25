"""HARVEST-OPS-001 BUILD SLICE 1: `_opener_kind_and_id` widening (proving
Harvest correctly reads traceability for every current BCA opener kind,
including a restored generation) and migration downgrade safety."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import harvest_service
from tests.test_leafy_harvest import _harvest, _line
from tests.test_leafy_harvest_correction import _correct, _only_source_line
from tests.test_production_disposition import _plate_scenario

pytestmark = pytest.mark.integration


def test_opener_resolver_understands_transplant_origin(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=180)
    from app.models.batch_carrier_assignment import BatchCarrierAssignment

    assignment = db_session.get(BatchCarrierAssignment, root_id)
    kind, opener_id = harvest_service._opener_kind_and_id(assignment)
    assert kind == "transplant"
    assert opener_id == assignment.opening_transplant_event_id


def test_opener_resolver_understands_production_disposition_restoration(db_session, active_context_with_farm) -> None:
    from app.models.batch_carrier_assignment import BatchCarrierAssignment
    from app.services import production_disposition_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = production_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=root_id, plant_loss_count=5, reason_code="dead", effective_time=t0 + timedelta(hours=1),
        note=None,
    )
    event = db_session.execute(
        text("SELECT id FROM production_disposition_events WHERE command_id = :cid"), {"cid": record.id}
    ).scalar_one()
    production_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=event, corrected=None,
    )
    restored = db_session.execute(
        text(
            "SELECT id FROM batch_carrier_assignments "
            "WHERE opening_production_disposition_reversal_event_id IS NOT NULL AND restored_from_batch_carrier_assignment_id = :root"
        ),
        {"root": root_id},
    ).scalar_one()
    assignment = db_session.get(BatchCarrierAssignment, restored)
    kind, opener_id = harvest_service._opener_kind_and_id(assignment)
    assert kind == "production_disposition_reversal"
    assert opener_id == assignment.opening_production_disposition_reversal_event_id


def test_opener_resolver_understands_harvest_restoration(db_session, active_context_with_farm) -> None:
    from app.models.batch_carrier_assignment import BatchCarrierAssignment

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    _correct(
        db_session, tenant, farm, user, line.id,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    restored = db_session.execute(
        text(
            "SELECT id FROM batch_carrier_assignments "
            "WHERE opening_harvest_population_reversal_event_id IS NOT NULL AND restored_from_batch_carrier_assignment_id = :root"
        ),
        {"root": root_id},
    ).scalar_one()
    assignment = db_session.get(BatchCarrierAssignment, restored)
    kind, opener_id = harvest_service._opener_kind_and_id(assignment)
    assert kind == "harvest_reversal"
    assert opener_id == assignment.opening_harvest_population_reversal_event_id


def test_harvest_from_production_disposition_restored_bca(db_session, active_context_with_farm) -> None:
    """A Plate BCA restored by a Production Disposition correction can
    later be harvested correctly."""
    from app.services import production_disposition_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    record = production_disposition_service.record_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        batch_carrier_assignment_id=root_id, plant_loss_count=5, reason_code="dead", effective_time=t0 + timedelta(hours=1),
        note=None,
    )
    event = db_session.execute(
        text("SELECT id FROM production_disposition_events WHERE command_id = :cid"), {"cid": record.id}
    ).scalar_one()
    production_disposition_service.correct_disposition(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        target_event_id=event, corrected=None,
    )
    from app.services import leafy_population_service

    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 5
    # The ORIGINAL root BCA is now released -- Harvest must target the
    # CURRENTLY ACTIVE restored generation, never the historical root id.
    active_id = leafy_population_service.resolve_active_assignment_id_for_root(
        db_session, root_batch_carrier_assignment_id=root_id
    )
    assert active_id != root_id

    harvest_event = _harvest(
        db_session, tenant, farm, user, batch.id, [_line(active_id, 3, "1.200")], effective_time=t0 + timedelta(hours=2)
    )
    assert harvest_event is not None
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 2


def test_harvest_from_harvest_restored_bca(db_session, active_context_with_farm) -> None:
    """A Plate BCA restored by a Harvest correction can later be
    harvested again correctly."""
    from app.services import leafy_population_service

    tenant, user, _headers, farm = active_context_with_farm
    batch, root_id, t0 = _plate_scenario(db_session, tenant, user, farm, opening_count=5)
    event = _harvest(db_session, tenant, farm, user, batch.id, [_line(root_id, 5, "2.500")], effective_time=t0 + timedelta(hours=1))
    line = _only_source_line(db_session, event)
    _correct(
        db_session, tenant, farm, user, line.id,
        corrected_harvested_weight_kg=Decimal("2.000"), corrected_whole_unit_count=4,
    )
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 1
    active_id = leafy_population_service.resolve_active_assignment_id_for_root(
        db_session, root_batch_carrier_assignment_id=root_id
    )
    assert active_id != root_id

    second_event = _harvest(
        db_session, tenant, farm, user, batch.id, [_line(active_id, 1, "0.400")], effective_time=t0 + timedelta(hours=2)
    )
    assert second_event is not None
    assert leafy_population_service.get_current_living_population(db_session, root_batch_carrier_assignment_id=root_id) == 0


# =====================================================================
# Migration downgrade safety
# =====================================================================

API_ROOT_MIGRATIONS_HEAD = "b8f3c6d1e947"
_PRE_MIGRATION_REVISION = "a5c9e21f7b64"


def _cfg() -> Config:
    from pathlib import Path

    api_root = Path(__file__).resolve().parent.parent
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


def _resolve_head_revision(cfg: Config) -> str:
    return ScriptDirectory.from_config(cfg).get_current_head()


def _assert_at_head(test_engine) -> None:
    with test_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    expected_head = _resolve_head_revision(_cfg())
    assert current == expected_head, "a blocked downgrade must leave the database at Alembic head"


def _cleanup(test_engine, tenant_id: uuid.UUID) -> None:
    from tests._traceability_scenario import cleanup_traceability_scenario

    cleanup_traceability_scenario(test_engine, tenant_id)


def test_downgrade_blocked_when_harvest_population_history_exists(test_engine, alembic_head_restore) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service
    from tests.test_leafy_production_transfer import (
        _leafy_setup, _nursery_plate_source_scenario, _production_plates, _record, _simple_allocation,
        _simple_destination, _simple_source,
    )

    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:8]
    tenant_id = None
    try:
        tenant = tenant_service.create_tenant(session, code=f"hguard-{suffix}", name="Harvest Guard Tenant")
        tenant_id = tenant.id
        user = user_service.create_user(
            session, oidc_issuer="hguard", oidc_subject=suffix, email=f"hguard-{suffix}@example.com",
            display_name="Harvest Guard User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Guard Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        s, aids = _nursery_plate_source_scenario(session, tenant, user, farm, opening_count=10)
        table_ids = _leafy_setup(session, tenant, user, farm)
        plates, _spec = _production_plates(session, tenant, user, farm, count=1)
        result = _record(
            session, tenant, farm, user, s["batch"],
            [_simple_source(aids[0])], [_simple_destination(plates[0].id, table_ids[0], count=10)],
            [_simple_allocation(aids[0], plates[0].id, 10)],
            effective_time=s["transfer_ready_time"] + timedelta(hours=1),
        )
        root_id = result.destination_lines[0].destination_batch_carrier_assignment_id
        _harvest(
            session, tenant, farm, user, s["batch"].id, [_line(root_id, 2, "0.800")],
            effective_time=s["transfer_ready_time"] + timedelta(hours=2),
        )
        session.commit()

        with pytest.raises(RuntimeError, match="harvest_population_events"):
            command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)

        _assert_at_head(test_engine)
    finally:
        session.close()
        conn.close()
        if tenant_id is not None:
            _cleanup(test_engine, tenant_id)


def test_downgrade_clean_when_no_harvest_population_history_exists(test_engine, alembic_head_restore) -> None:
    command.downgrade(_cfg(), _PRE_MIGRATION_REVISION)
    with test_engine.connect() as verify_conn:
        current = verify_conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        table_exists = verify_conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'harvest_population_events')"
            )
        ).scalar_one()
        column_exists = verify_conn.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'batch_carrier_assignments' "
                "AND column_name = 'opening_harvest_population_reversal_event_id')"
            )
        ).scalar_one()
    assert current == _PRE_MIGRATION_REVISION
    assert table_exists is False
    assert column_exists is False

    command.upgrade(_cfg(), "head")
    _assert_at_head(test_engine)
    with test_engine.connect() as verify_conn2:
        table_restored = verify_conn2.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'harvest_population_events')"
            )
        ).scalar_one()
    assert table_restored is True
