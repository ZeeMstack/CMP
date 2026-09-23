"""UX-OPS-001D0: committed (real-connection) Water Delivery scenario shared by
the End Delivery concurrency tests and the migration downgrade-guard tests.
Cleanup bypasses the append-only triggers via `session_replication_role =
replica`, and only ever against `cmp_test`."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    farm_service,
    membership_service,
    reservoir_operations_service,
    tenant_service,
    user_service,
    water_topology_service,
)


def require_cmp_test(test_engine) -> None:
    with test_engine.connect() as guard_conn:
        current_db = guard_conn.execute(text("SELECT current_database()")).scalar_one()
    if current_db != "cmp_test":
        raise RuntimeError(
            f"refusing to run privileged test cleanup (session_replication_role) against "
            f"database {current_db!r}; this cleanup is only permitted against 'cmp_test'"
        )


def build_open_delivery_scenario(test_engine) -> dict:
    """A committed tenant/farm/Reservoir/Circuit plus one ONGOING delivery
    (`effective_end = NULL`) that started an hour ago."""
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    session = Session(bind=conn)
    suffix = uuid.uuid4().hex[:10]
    try:
        tenant = tenant_service.create_tenant(session, code=f"wde-{suffix}", name="Water End Tenant")
        user = user_service.create_user(
            session, oidc_issuer="wde", oidc_subject=suffix, email=f"wde-{suffix}@example.com",
            display_name="Water End User",
        )
        membership_service.add_membership(
            session, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None
        )
        farm = farm_service.create_farm(
            session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Water End Farm",
            country_code="AE", city_region=None, timezone="Asia/Dubai",
        )
        reservoir = water_topology_service.register_reservoir(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RES-{suffix}",
            name="Reservoir", reservoir_type="nutrient_reservoir", nominal_capacity=None,
            nominal_capacity_uom_id=None, linked_asset_id=None, location_id=None, notes=None,
        )
        circuit = water_topology_service.register_irrigation_circuit(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"IC-{suffix}",
            name="Circuit", system_type="dwc", notes=None,
        )
        effective_start = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1)
        delivery = reservoir_operations_service.record_delivery_event(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
            irrigation_circuit_id=circuit.id, effective_start=effective_start, effective_end=None,
            delivered_volume=None, delivered_volume_uom_id=None, nutrient_mix_id=None, notes=None,
            client_command_id=uuid.uuid4(),
        )
        return {
            "tenant_id": tenant.id, "user_id": user.id, "farm_id": farm.id, "reservoir_id": reservoir.id,
            "irrigation_circuit_id": circuit.id, "delivery_id": delivery.id, "effective_start": effective_start,
        }
    finally:
        session.close()
        conn.close()


def cleanup_scenario(test_engine, tenant_id: uuid.UUID) -> None:
    require_cmp_test(test_engine)
    conn = test_engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text("SET session_replication_role = replica"))
        for table in (
            "water_delivery_end_events",
            "water_delivery_events",
            "irrigation_circuits",
            "reservoirs",
            "audit_events",
            "tenant_memberships",
            "farms",
        ):
            conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tid"), {"tid": tenant_id})
        conn.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    except Exception:
        trans.rollback()
        conn.execute(text("SET session_replication_role = DEFAULT"))
        conn.commit()
        raise
    else:
        conn.execute(text("SET session_replication_role = DEFAULT"))
        trans.commit()
    finally:
        conn.close()
