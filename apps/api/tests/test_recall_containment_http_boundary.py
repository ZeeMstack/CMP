"""PRE-COMMIT AUDIT (PILOT-READY-001): proves, over the real HTTP boundary,
the fix for a gap the previous service-layer-only pilot smoke test could
never have caught -- `RecallContainmentOpenError` was raised correctly by
`dispatch_service.record_dispatch`, `finished_goods_storage_service.
record_movement` (release), and `batch_derivation_service.split_batch`/
`merge_batches`, but three of their four routers (`app/api/dispatch.py`,
`app/api/finished_goods_storage.py`, `app/api/batch_derivations.py`) never
caught it -- an open Recall crashed the HTTP request with an unhandled 500
instead of the clean 409 `grading.py`/`packing.py` already returned.
Dispatch's own fix is proven end-to-end inside `test_pilot_e2e_smoke.py`;
this file covers the other two now-fixed routers directly."""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_db
from app.main import app
from tests._recall_scenario import (
    build_committed_tenant_farm,
    cleanup_recall_scenario,
    committed_connection,
    create_cold_store_position,
    harvest_all,
    open_case,
    pack_lot,
)
from tests._traceability_scenario import build_batch_with_assignments, now as _now


def _iso(dt):
    return dt.isoformat()


@pytest.mark.integration
def test_storage_release_blocked_by_open_recall_returns_409_over_http(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, user, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(db, tenant, user, farm, carrier_count=1)
            _event, produce_lot_id = harvest_all(
                db, tenant, user, farm, batch_id=scaffold["batch"].id, assignment_ids=scaffold["assignment_ids"]
            )
            fg_lot_id, _packing_event_id = pack_lot(db, tenant, user, farm, produce_lot_id=produce_lot_id)
            position = create_cold_store_position(db, tenant, user, farm)

            headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
            app.dependency_overrides[get_db] = lambda: db
            client = TestClient(app)
            client.__enter__()
            try:
                resp = client.post(
                    f"/farms/{farm.id}/finished-goods-storage-movements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(_now()),
                        "finished_goods_lot_id": str(fg_lot_id), "movement_kind": "place", "source_location_id": None,
                        "destination_location_id": str(position.id), "moved_weight_kg": "1.000", "moved_package_count": 1,
                        "note": None,
                    },
                )
                assert resp.status_code == 201, resp.text

                open_case(db, tenant, farm, user, finished_goods_lot_id=fg_lot_id)
                db.commit()

                resp = client.post(
                    f"/farms/{farm.id}/finished-goods-storage-movements", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(_now()),
                        "finished_goods_lot_id": str(fg_lot_id), "movement_kind": "release",
                        "source_location_id": str(position.id), "destination_location_id": None,
                        "moved_weight_kg": "1.000", "moved_package_count": 1, "note": None,
                    },
                )
                assert resp.status_code == 409, resp.text
                assert resp.status_code != 500
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_batch_split_blocked_by_open_recall_returns_409_over_http(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as db:
            tenant, user, farm = build_committed_tenant_farm(db)
            tenant_id = tenant.id
            scaffold = build_batch_with_assignments(db, tenant, user, farm, carrier_count=2)
            batch_id = scaffold["batch"].id
            open_case(db, tenant, farm, user, crop_batch_id=batch_id)
            db.commit()

            headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
            app.dependency_overrides[get_db] = lambda: db
            client = TestClient(app)
            client.__enter__()
            try:
                resp = client.post(
                    f"/farms/{farm.id}/crop-batches/{batch_id}/split", headers=headers,
                    json={
                        "client_command_id": str(uuid.uuid4()), "effective_time": _iso(_now()), "note": None,
                        "outputs": [
                            {"output_batch_code": f"SIDE-1-{uuid.uuid4().hex[:6]}", "source_assignment_ids": [str(scaffold["assignment_ids"][0])]},
                            {"output_batch_code": f"SIDE-2-{uuid.uuid4().hex[:6]}", "source_assignment_ids": [str(scaffold["assignment_ids"][1])]},
                        ],
                    },
                )
                assert resp.status_code == 409, resp.text
                assert resp.status_code != 500
            finally:
                client.__exit__(None, None, None)
                app.dependency_overrides.pop(get_db, None)
    finally:
        if tenant_id is not None:
            cleanup_recall_scenario(test_engine, tenant_id)
