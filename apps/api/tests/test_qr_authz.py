"""PILOT-SCAN-001 FINAL SECURITY CLOSURE: a compact, parametrized proof that
`app.api.qr`'s dynamic, entity-type-dependent permission gate holds for
every one of the eight supported entity types -- the behavioral companion
to this module's own exemption comments in
`test_authz_read_enforcement_architecture.py`/
`test_authz_mutation_enforcement_architecture.py` (a generic QR resolver
cannot carry one static `Permission` the way the rest of the codebase's
routes do, so this file is what proves it is not silently unauthorized).

Role choice is not arbitrary -- it is the REAL existing policy
(`app/core/permissions.py::ROLE_PERMISSIONS`), never weakened to make the
test easy:

- `storekeeper` lacks EVERY one of the eight `.manage`-tier permissions
  this ticket's `ENTITY_PERMISSIONS` map uses (`crop_batch.manage`,
  `location.manage`, `carrier.manage`, `asset.manage`, `sowing.manage`,
  `harvest.manage`, `grading.manage`, `packing.manage`) -- the universal
  "cannot generate/print" negative case for all eight.
- `storekeeper` ALSO lacks five of the eight `.read`-tier permissions
  (`crop_batch.read`, `sowing.read`, `harvest.read`, `grading.read`,
  `packing.read`) -- the "cannot even scan" negative case for those five.
  `location.read`/`carrier.read`/`asset.read` are granted to literally
  every role in the current catalog (including storekeeper) -- there is
  no role to construct a read-bypass negative for those three, and this
  test says so explicitly rather than inventing one.
- `qc_officer` holds every one of the eight `.read` permissions (broad
  cross-chain read visibility is its whole point) while lacking every one
  of the eight `.manage` permissions -- a second, independent proof of the
  read/manage split for every entity type.
"""
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import get_db, get_engine
from app.main import app
from app.services import asset_service, location_service, membership_service, user_service
from tests._traceability_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_traceability_scenario,
    committed_connection,
    harvest_all,
    now,
    pack_lot,
)

# entity_type -> whether `location.read`/`carrier.read`/`asset.read`-style
# universal grant applies (True: storekeeper CAN resolve it; False:
# storekeeper lacks the read permission and is denied).
STOREKEEPER_CAN_RESOLVE = {
    "crop_batch": False,
    "location": True,
    "carrier": True,
    "asset": True,
    "batch_carrier_assignment": False,
    "harvested_produce_lot": False,
    "graded_produce_lot": False,
    "finished_goods_lot": False,
}
ENTITY_TYPES = list(STOREKEEPER_CAN_RESOLVE)


@pytest.mark.integration
def test_qr_entity_type_permission_matrix(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, admin, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(db, tenant, admin, farm, carrier_count=1)
            batch_id = scaffold["batch"].id
            carrier_id = scaffold["carriers"][0].id
            assignment_id = scaffold["assignment_ids"][0]

            asset = asset_service.register_asset(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=admin.id,
                asset_type_code="germination_trolley", code="QR-TROLLEY-0001", name="Trolley", commissioned_date=None,
            )

            _, hpl_id = harvest_all(
                db, tenant, admin, farm, batch_id=batch_id, assignment_ids=[assignment_id],
                weight_per_line=Decimal("5.000"),
            )
            fg_lot_id, packing_event_id = pack_lot(
                db, tenant, admin, farm, produce_lot_id=hpl_id, weight=Decimal("5.000"), package_count=5,
            )
            gpl_id = db.execute(
                text("SELECT graded_produce_lot_id FROM packing_input_lines WHERE packing_event_id = :eid"),
                {"eid": packing_event_id},
            ).scalar_one()

            storekeeper = user_service.create_user(
                db, oidc_issuer="qr-authz", oidc_subject=f"storekeeper-{uuid.uuid4().hex[:8]}",
                email=f"storekeeper-{uuid.uuid4().hex[:8]}@example.com", display_name="Storekeeper",
            )
            membership_service.add_membership(
                db, tenant_id=tenant.id, user_id=storekeeper.id, role_code="storekeeper", actor_user_id=None,
            )
            qc_officer = user_service.create_user(
                db, oidc_issuer="qr-authz", oidc_subject=f"qc-{uuid.uuid4().hex[:8]}",
                email=f"qc-{uuid.uuid4().hex[:8]}@example.com", display_name="QC Officer",
            )
            membership_service.add_membership(
                db, tenant_id=tenant.id, user_id=qc_officer.id, role_code="qc_officer", actor_user_id=None,
            )
            db.commit()

            farm_id, admin_id, storekeeper_id, qc_officer_id = farm.id, admin.id, storekeeper.id, qc_officer.id

            # A real occupiable Location, independent of the Carrier scaffold
            # above (CLAUDE.md's own leafy-greens zone->span->grow_table
            # chain, mirroring test_qr_scan_acceptance.py's own helper).
            greenhouse = location_service.create_location(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=admin.id, location_type_code="greenhouse",
                code="qr-authz-gh", name="Greenhouse", parent_location_id=None,
                greenhouse_classification="leafy_greens", occupiable=None,
            )
            zone = location_service.create_location(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=admin.id, location_type_code="zone",
                code="qr-authz-z", name="Zone", parent_location_id=greenhouse.id,
                greenhouse_classification=None, occupiable=None,
            )
            span = location_service.create_location(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=admin.id, location_type_code="span",
                code="qr-authz-sp", name="Span", parent_location_id=zone.id,
                greenhouse_classification=None, occupiable=None,
            )
            table = location_service.create_location(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=admin.id, location_type_code="grow_table",
                code="qr-authz-gt", name="Table", parent_location_id=span.id,
                greenhouse_classification=None, occupiable=True,
            )
            db.commit()

            entity_ids = {
                "crop_batch": batch_id,
                "location": table.id,
                "carrier": carrier_id,
                "asset": asset.id,
                "batch_carrier_assignment": assignment_id,
                "harvested_produce_lot": hpl_id,
                "graded_produce_lot": gpl_id,
                "finished_goods_lot": fg_lot_id,
            }

            admin_headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(admin_id)}
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_engine] = lambda: test_engine
            client = TestClient(app)
            client.__enter__()
            try:
                tokens: dict[str, str] = {}
                for entity_type in ENTITY_TYPES:
                    resp = client.post(
                        f"/farms/{farm_id}/qr/{entity_type}/{entity_ids[entity_type]}/generate", headers=admin_headers
                    )
                    assert resp.status_code == 200, f"{entity_type}: {resp.text}"
                    tokens[entity_type] = resp.json()["token"]

                storekeeper_headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(storekeeper_id)}
                qc_officer_headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(qc_officer_id)}

                with committed_connection(test_engine) as db2:
                    other_tenant, other_user, _other_farm = build_committed_tenant_farm(db2)
                    db2.commit()
                    other_tenant_id, other_user_id = other_tenant.id, other_user.id
                other_headers = {"X-Dev-Tenant-Id": str(other_tenant_id), "X-Dev-User-Id": str(other_user_id)}

                for entity_type in ENTITY_TYPES:
                    token = tokens[entity_type]

                    # 1. an appropriately authorized same-tenant user can
                    # resolve it (tenant_admin: every permission).
                    resp = client.get(f"/qr/{token}", headers=admin_headers)
                    assert resp.status_code == 200, f"{entity_type} admin resolve: {resp.text}"
                    assert resp.json()["entity_type"] == entity_type

                    # qc_officer holds every .read permission -- resolves
                    # every entity type -- but every .manage permission is
                    # denied -- can never generate/print, for any type.
                    resp = client.get(f"/qr/{token}", headers=qc_officer_headers)
                    assert resp.status_code == 200, f"{entity_type} qc_officer resolve: {resp.text}"
                    resp = client.post(
                        f"/farms/{farm_id}/qr/{entity_type}/{entity_ids[entity_type]}/generate",
                        headers=qc_officer_headers,
                    )
                    assert resp.status_code == 403, f"{entity_type} qc_officer generate: {resp.text}"
                    resp = client.post(
                        f"/qr/{token}/print", json={"template": "t", "template_version": "v1"},
                        headers=qc_officer_headers,
                    )
                    assert resp.status_code == 403, f"{entity_type} qc_officer print: {resp.text}"

                    # 2. storekeeper: an unauthorized role must never use the
                    # generic QR route as a bypass. It can never
                    # generate/print (lacks every .manage permission this
                    # ticket uses); it can only resolve/scan the three
                    # entity types where read is genuinely universal policy.
                    resp = client.get(f"/qr/{token}", headers=storekeeper_headers)
                    if STOREKEEPER_CAN_RESOLVE[entity_type]:
                        assert resp.status_code == 200, f"{entity_type} storekeeper resolve: {resp.text}"
                    else:
                        assert resp.status_code == 403, f"{entity_type} storekeeper resolve: {resp.text}"
                    resp = client.post(
                        f"/farms/{farm_id}/qr/{entity_type}/{entity_ids[entity_type]}/generate",
                        headers=storekeeper_headers,
                    )
                    assert resp.status_code == 403, f"{entity_type} storekeeper generate: {resp.text}"

                    # 3. foreign tenant cannot resolve it -- scoped 404,
                    # never a 403 (never confirms a token exists at all).
                    resp = client.get(f"/qr/{token}", headers=other_headers)
                    assert resp.status_code == 404, f"{entity_type} foreign tenant: {resp.text}"

                    # 4. an invalid/random token never leaks whether the
                    # underlying entity exists -- identical 404, same-tenant.
                    resp = client.get(f"/qr/{token}-corrupted", headers=admin_headers)
                    assert resp.status_code == 404, f"{entity_type} invalid token: {resp.text}"
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
                app.dependency_overrides.pop(get_engine, None)
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
