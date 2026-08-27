"""CMP-019 HTTP acceptance test: exercises the three traceability GET
routes end-to-end through the real FastAPI app, proving the `get_engine`
dependency-override wiring works (the trace service's own dedicated
connection must see data committed by a separate connection, not the
request's own uncommitted `db_session`), that no mutation route exists,
and that cross-tenant access returns 404."""
from decimal import Decimal

import pytest

from tests._traceability_scenario import (
    build_batch_with_assignments,
    build_committed_tenant_farm,
    cleanup_traceability_scenario,
    committed_connection,
    harvest_all,
    pack_lot,
)


@pytest.mark.integration
def test_traceability_acceptance_flow(client, test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(session, tenant, user, farm, carrier_count=1)
            _, produce_lot_id = harvest_all(session, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"])
            fg_lot_id, _ = pack_lot(session, tenant, user, farm, produce_lot_id=produce_lot_id, weight=Decimal("5.000"), package_count=5)
            session.commit()
            farm_id, batch_id, user_id = farm.id, scaffold["batch"].id, user.id

        headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user_id)}

        resp = client.get(f"/farms/{farm_id}/traceability/finished-goods-lots/{fg_lot_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["subject"]["finished_goods_lot_id"] == str(fg_lot_id)
        assert body["completeness"]["trace_complete"] is True
        # POSTHARVEST-OPS-001F: GPL is a first-class public traceability entity.
        assert len(body["graded_produce_lots"]) == 1
        assert len(body["grading_events"]) == 1
        assert body["packing_inputs"][0]["graded_produce_lot_id"] == body["graded_produce_lots"][0]["graded_produce_lot_id"]

        resp = client.get(f"/farms/{farm_id}/traceability/crop-batches/{batch_id}/impact", headers=headers)
        assert resp.status_code == 200, resp.text
        batch_impact = resp.json()
        assert batch_impact["subject_batch_id"] == str(batch_id)
        assert len(batch_impact["graded_produce_lots"]) == 1
        assert batch_impact["summary"]["affected_graded_produce_lot_count"] == 1

        resp = client.get(f"/farms/{farm_id}/traceability/harvested-produce-lots/{produce_lot_id}/impact", headers=headers)
        assert resp.status_code == 200, resp.text
        hpl_impact = resp.json()
        assert hpl_impact["subject_harvested_produce_lot_id"] == str(produce_lot_id)
        assert len(hpl_impact["graded_produce_lots"]) == 1

        # No mutation routes anywhere in this API.
        assert client.post(f"/farms/{farm_id}/traceability/finished-goods-lots/{fg_lot_id}", headers=headers).status_code in (404, 405)
        assert client.put(f"/farms/{farm_id}/traceability/finished-goods-lots/{fg_lot_id}", headers=headers).status_code in (404, 405)
        assert client.delete(f"/farms/{farm_id}/traceability/finished-goods-lots/{fg_lot_id}", headers=headers).status_code in (404, 405)

        # Cross-tenant access returns 404, never leaking existence.
        with committed_connection(test_engine) as session2:
            other_tenant, other_user, other_farm = build_committed_tenant_farm(session2)
            session2.commit()
            other_tenant_id, other_farm_id, other_user_id = other_tenant.id, other_farm.id, other_user.id
        try:
            other_headers = {"X-Dev-Tenant-Id": str(other_tenant_id), "X-Dev-User-Id": str(other_user_id)}
            resp = client.get(f"/farms/{other_farm_id}/traceability/finished-goods-lots/{fg_lot_id}", headers=other_headers)
            assert resp.status_code == 404
        finally:
            cleanup_traceability_scenario(test_engine, other_tenant_id)
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)
