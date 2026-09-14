"""PILOT-SCAN-001 HTTP acceptance test: exercises QR generation, scan
resolution, and print/reprint audit end-to-end through the real FastAPI
app. Covers the ticket's own "high-value acceptance tests" list: idempotent
generation, cross-tenant denial, invalid-token denial, dynamic occupancy
resolution after a movement, exact placement sub-context (never collapsed
into the parent Batch), and reprint audit that creates no second QR
identity and no business event.

Uses `test_pilot_e2e_smoke.py`'s own pattern -- a `TestClient` bound to a
single `committed_connection`-sourced Session for the whole flow -- rather
than the ordinary `client`/`db_session` pytest fixtures: every service
call here does its own real `db.commit()`, which only truly releases a
just-acquired row lock (e.g. the FK-referencing share lock a QR-generate
INSERT takes on its target Carrier/Batch row) under a plain, un-nested
Session. The `client`/`db_session` fixtures instead wrap the whole test in
one outer transaction with SAVEPOINT-based "commits" that never release
real locks until fixture teardown -- fine for the traceability acceptance
test (read-only HTTP calls), but this test also mutates (generate/print),
and a later step (a second Movement, or this test's own cleanup) touching
the same already-locked row would deadlock against that.
"""
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import get_db, get_engine
from app.main import app
from app.services import location_service, movement_service
from tests._traceability_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_traceability_scenario,
    committed_connection,
    harvest_all,
    now,
    pack_lot,
)


def _make_grow_tables(session, tenant, user, farm, *, suffix, count=2):
    """CLAUDE.md's own leafy-greens chain (zone -> span -> grow table,
    mandatory, no shortcuts) -- `cultivation_plate` is the one Carrier type
    the domain already lets occupy a `grow_table` Location directly
    (9ca4ac801827)."""
    greenhouse = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code=f"gh-{suffix}", name="Greenhouse",
        parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
    )
    zone = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="zone", code=f"z-{suffix}", name="Zone",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    span = location_service.create_location(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="span", code=f"sp-{suffix}", name="Span",
        parent_location_id=zone.id, greenhouse_classification=None, occupiable=None,
    )
    return [
        location_service.create_location(
            session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            location_type_code="grow_table", code=f"gt-{suffix}-{n:02d}", name=f"Table {n}",
            parent_location_id=span.id, greenhouse_classification=None, occupiable=True,
        )
        for n in range(1, count + 1)
    ]


@pytest.mark.integration
def test_qr_scan_acceptance_flow(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, user, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(
                db, tenant, user, farm, carrier_count=1, carrier_type_code="cultivation_plate"
            )
            batch_id = scaffold["batch"].id
            carrier = scaffold["carriers"][0]
            assignment_id = scaffold["assignment_ids"][0]

            chamber_a, chamber_b = _make_grow_tables(db, tenant, user, farm, suffix="loc", count=2)
            movement_service.execute_movement(
                db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                client_command_id=uuid.uuid4(), effective_time=now(), occupant_kind="carrier",
                occupant_id=carrier.id, destination_kind="location", destination_id=chamber_a.id, reason=None,
            )

            _, hpl_id = harvest_all(
                db, tenant, user, farm, batch_id=batch_id, assignment_ids=[assignment_id],
                weight_per_line=Decimal("5.000"),
            )
            fg_lot_id, packing_event_id = pack_lot(
                db, tenant, user, farm, produce_lot_id=hpl_id, weight=Decimal("5.000"), package_count=5,
            )
            gpl_id = db.execute(
                text("SELECT graded_produce_lot_id FROM packing_input_lines WHERE packing_event_id = :eid"),
                {"eid": packing_event_id},
            ).scalar_one()
            db.commit()
            farm_id, user_id, carrier_id = farm.id, user.id, carrier.id
            chamber_b_id = chamber_b.id

            headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user_id)}
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_engine] = lambda: test_engine
            client = TestClient(app)
            client.__enter__()
            try:
                # --- 1/2: generate is idempotent -----------------------------
                resp = client.post(f"/farms/{farm_id}/qr/carrier/{carrier_id}/generate", headers=headers)
                assert resp.status_code == 200, resp.text
                carrier_qr = resp.json()
                assert carrier_qr["entity_type"] == "carrier"
                token = carrier_qr["token"]
                assert len(token) >= 24

                resp2 = client.post(f"/farms/{farm_id}/qr/carrier/{carrier_id}/generate", headers=headers)
                assert resp2.status_code == 200, resp2.text
                assert resp2.json()["id"] == carrier_qr["id"]
                assert resp2.json()["token"] == token

                # --- 4: invalid token ------------------------------------------
                resp = client.get("/qr/not-a-real-token", headers=headers)
                assert resp.status_code == 404

                # --- 6: Carrier scan resolves CURRENT occupancy dynamically ---
                resp = client.get(f"/qr/{token}", headers=headers)
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["entity_type"] == "carrier"
                assert body["code"] == carrier.code
                assert body["current_location"]["codes"][-1] == chamber_a.code
                assert body["current_batch"]["code"] == scaffold["batch"].code

                # Move the carrier -- the SAME QR token must now resolve the NEW
                # location.
                resp = client.post(
                    f"/farms/{farm_id}/movements",
                    headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()),
                        "effective_time": now().isoformat(),
                        "occupant": {"kind": "carrier", "id": str(carrier_id)},
                        "destination": {"kind": "location", "id": str(chamber_b_id)},
                    },
                )
                assert resp.status_code == 201, resp.text

                resp = client.get(f"/qr/{token}", headers=headers)
                assert resp.status_code == 200
                assert resp.json()["current_location"]["codes"][-1] == chamber_b.code

                # --- Placement QR resolves exact sub-context, not merely the
                # parent Batch -------------------------------------------------
                resp = client.post(
                    f"/farms/{farm_id}/qr/batch_carrier_assignment/{assignment_id}/generate", headers=headers
                )
                assert resp.status_code == 200, resp.text
                placement_token = resp.json()["token"]
                resp = client.get(f"/qr/{placement_token}", headers=headers)
                assert resp.status_code == 200, resp.text
                placement_body = resp.json()
                assert placement_body["entity_type"] == "batch_carrier_assignment"
                assert placement_body["batch"]["code"] == scaffold["batch"].code
                assert placement_body["carrier_code"] == carrier.code

                # --- Batch QR ----------------------------------------------------
                resp = client.post(f"/farms/{farm_id}/qr/crop_batch/{batch_id}/generate", headers=headers)
                assert resp.status_code == 200, resp.text
                batch_token = resp.json()["token"]
                resp = client.get(f"/qr/{batch_token}", headers=headers)
                assert resp.status_code == 200, resp.text
                batch_body = resp.json()
                assert batch_body["entity_type"] == "crop_batch"
                assert batch_body["code"] == scaffold["batch"].code
                assert batch_body["crop"]["code"] == scaffold["crop"].code

                # --- Harvested / Graded / Finished Goods lot QRs -----------------
                lot_tokens: dict[str, str] = {}
                for entity_type, entity_id, expected_code_query in (
                    ("harvested_produce_lot", hpl_id, "SELECT code FROM harvested_produce_lots WHERE id = :id"),
                    ("graded_produce_lot", gpl_id, "SELECT code FROM graded_produce_lots WHERE id = :id"),
                    ("finished_goods_lot", fg_lot_id, "SELECT code FROM finished_goods_lots WHERE id = :id"),
                ):
                    resp = client.post(f"/farms/{farm_id}/qr/{entity_type}/{entity_id}/generate", headers=headers)
                    assert resp.status_code == 200, resp.text
                    lot_token = resp.json()["token"]
                    lot_tokens[entity_type] = lot_token
                    resp = client.get(f"/qr/{lot_token}", headers=headers)
                    assert resp.status_code == 200, resp.text
                    lot_body = resp.json()
                    assert lot_body["entity_type"] == entity_type
                    expected_code = db.execute(text(expected_code_query), {"id": entity_id}).scalar_one()
                    assert lot_body["code"] == expected_code

                # --- Location QR ---------------------------------------------------
                resp = client.post(f"/farms/{farm_id}/qr/location/{chamber_b_id}/generate", headers=headers)
                assert resp.status_code == 200, resp.text
                location_token = resp.json()["token"]
                resp = client.get(f"/qr/{location_token}", headers=headers)
                assert resp.status_code == 200, resp.text
                location_body = resp.json()
                assert location_body["entity_type"] == "location"
                assert location_body["code"] == chamber_b.code
                assert any(o["code"] == carrier.code for o in location_body["occupants"])

                # --- 8: reprint audit does not mint a second QR or a business
                # event -----------------------------------------------------------
                audit_count_before = db.execute(
                    text("SELECT count(*) FROM audit_events WHERE action = 'qr_label_print_requested'")
                ).scalar_one()
                harvest_events_before = db.execute(text("SELECT count(*) FROM harvest_events")).scalar_one()
                qr_row_count_before = db.execute(text("SELECT count(*) FROM qr_identifiers")).scalar_one()

                print_payload = {"template": "carrier_small", "template_version": "v1"}
                resp = client.post(f"/qr/{token}/print", json=print_payload, headers=headers)
                assert resp.status_code == 200, resp.text
                assert resp.json()["is_reprint"] is False

                reprint_payload = {"template": "carrier_small", "template_version": "v1", "reason": "label damaged"}
                resp = client.post(f"/qr/{token}/print", json=reprint_payload, headers=headers)
                assert resp.status_code == 200, resp.text
                assert resp.json()["is_reprint"] is True

                audit_count_after = db.execute(
                    text("SELECT count(*) FROM audit_events WHERE action = 'qr_label_print_requested'")
                ).scalar_one()
                harvest_events_after = db.execute(text("SELECT count(*) FROM harvest_events")).scalar_one()
                qr_row_count_after = db.execute(text("SELECT count(*) FROM qr_identifiers")).scalar_one()
                assert audit_count_after == audit_count_before + 2
                assert harvest_events_after == harvest_events_before
                assert qr_row_count_after == qr_row_count_before

                # Reprinting again returns the exact same QR identity.
                resp = client.get(f"/qr/{token}", headers=headers)
                assert resp.json()["qr_identifier_id"] == carrier_qr["id"]

                # An operational/lot label's reprint requires a reason
                # (a permanent Carrier/Asset/Location label, tested above,
                # never does).
                hpl_token = lot_tokens["harvested_produce_lot"]
                resp = client.post(
                    f"/qr/{hpl_token}/print", json={"template": "hpl_standard", "template_version": "v1"},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text  # first print -- never a reprint, no reason needed
                resp = client.post(
                    f"/qr/{hpl_token}/print", json={"template": "hpl_standard", "template_version": "v1"},
                    headers=headers,
                )
                assert resp.status_code == 400, resp.text
                resp = client.post(
                    f"/qr/{hpl_token}/print",
                    json={"template": "hpl_standard", "template_version": "v1", "reason": "torn in transit"},
                    headers=headers,
                )
                assert resp.status_code == 200, resp.text
                assert resp.json()["is_reprint"] is True

                # --- 3: foreign tenant resolution is denied/scoped 404 -----------
                with committed_connection(test_engine) as db2:
                    other_tenant, other_user, other_farm = build_committed_tenant_farm(db2)
                    db2.commit()
                    other_tenant_id, other_user_id = other_tenant.id, other_user.id
                other_headers = {"X-Dev-Tenant-Id": str(other_tenant_id), "X-Dev-User-Id": str(other_user_id)}
                resp = client.get(f"/qr/{token}", headers=other_headers)
                assert resp.status_code == 404
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
                app.dependency_overrides.pop(get_engine, None)
    finally:
        if other_tenant_id is not None:
            cleanup_traceability_scenario(test_engine, other_tenant_id)
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_batch_qr_shows_every_simultaneous_active_placement_separately(test_engine) -> None:
    """PILOT-SCAN-001D proof 10: a Batch occupying more than one physical
    Carrier at once (the same shape a CMP-012 split produces -- several
    simultaneously active `BatchCarrierAssignment`s under one Batch) must
    show each one as its own distinct placement on the Batch's own QR scan
    -- never collapsed into a single ambiguous "the batch is somewhere"
    fact. Uses `resolve_scan_context`'s unchanged `crop_batch` branch
    (`qr_service.py`), which already aggregates one `PlacementSummary` per
    active assignment -- this proves that existing aggregation actually
    surfaces >1 placement end-to-end through the real API, not just that
    the code path exists."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, user, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(
                db, tenant, user, farm, carrier_count=2, carrier_type_code="cultivation_plate"
            )
            batch_id = scaffold["batch"].id
            carrier_codes = {c.code for c in scaffold["carriers"]}
            db.commit()

            headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
            app.dependency_overrides[get_db] = lambda: db
            app.dependency_overrides[get_engine] = lambda: test_engine
            client = TestClient(app)
            client.__enter__()
            try:
                resp = client.post(f"/farms/{farm.id}/qr/crop_batch/{batch_id}/generate", headers=headers)
                assert resp.status_code == 200, resp.text
                token = resp.json()["token"]

                resp = client.get(f"/qr/{token}", headers=headers)
                assert resp.status_code == 200, resp.text
                body = resp.json()
                assert body["entity_type"] == "crop_batch"
                placements = body["placements"]
                assert len(placements) == 2
                assert {p["carrier_code"] for p in placements} == carrier_codes
                # Two distinct placement identities, never collapsed into one.
                assert len({p["batch_carrier_assignment_id"] for p in placements}) == 2
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
                app.dependency_overrides.pop(get_engine, None)
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
