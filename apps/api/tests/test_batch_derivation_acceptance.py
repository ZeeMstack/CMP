"""API-level acceptance flow for CMP-012 split and merge: farm -> crop/variety/
production-system -> workflow -> published version -> batch -> sown carriers ->
split into two output batches -> re-merge those two outputs into one -> lineage,
retry, and cross-batch state checks. All via the HTTP API."""
import uuid
from datetime import datetime, timezone

import pytest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.mark.integration
def test_split_then_merge_acceptance_flow(client, active_context, db_session) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Derivation Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    crop = client.post(
        "/crops", headers=headers,
        json={"code": f"crop-{suffix}", "common_name": "Iceberg", "crop_category": "leafy_green"},
    ).json()
    variety = client.post(
        f"/crops/{crop['id']}/varieties", headers=headers, json={"code": f"var-{suffix}", "name": "Mamutik"}
    ).json()
    production_system = client.post(
        "/production-systems", headers=headers, json={"code": f"ps-{suffix}", "name": "Nursery Tray"}
    ).json()
    workflow = client.post(
        "/workflows", headers=headers,
        json={
            "crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": production_system["id"],
            "code": f"wf-{suffix}", "name": "Workflow",
        },
    ).json()
    version = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
    seeding = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={
            "code": "SEEDING", "name": "Seeding", "display_order": 0, "stage_category": "seeding",
            "is_start": True, "is_terminal": False, "required_carrier_type_code": "seed_tray",
        },
    ).json()
    complete = client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
        json={"code": "COMPLETE", "name": "Complete", "display_order": 1, "stage_category": "completed", "is_start": False, "is_terminal": True},
    ).json()
    client.post(
        f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
        json={
            "from_stage_id": seeding["id"], "to_stage_id": complete["id"], "code": "ADVANCE-1", "name": "Advance 1",
        },
    )
    publish_resp = client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
    assert publish_resp.status_code == 200

    batch_resp = client.post(
        f"/farms/{farm_id}/crop-batches", headers=headers,
        json={
            "code": f"BATCH-{suffix}", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()),
            "effective_time": _now_iso(),
        },
    )
    assert batch_resp.status_code == 201
    batch = batch_resp.json()

    seed_lot = client.post(
        f"/farms/{farm_id}/seed-lots", headers=headers,
        json={"crop_id": crop["id"], "variety_id": variety["id"], "code": f"lot-{suffix}"},
    ).json()

    carriers = [
        client.post(
            f"/farms/{farm_id}/carriers", headers=headers,
            json={"carrier_type_code": "seed_tray", "code": f"tray-{suffix}-{n}"},
        ).json()
        for n in range(4)
    ]
    sow_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [
                {"carrier_id": c["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 100, "seed_count": 100}
                for c in carriers
            ],
        },
    )
    assert sow_resp.status_code == 201

    assignments = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers).json()
    assignment_by_carrier_id = {a["carrier"]["id"]: a["id"] for a in assignments}
    assignment_ids = [assignment_by_carrier_id[c["id"]] for c in carriers]

    # 1-2. Split the source batch into two new batch codes, partitioning assignments.
    split_command_id = str(uuid.uuid4())
    split_payload = {
        "client_command_id": split_command_id, "effective_time": _now_iso(),
        "outputs": [
            {"output_batch_code": f"SPLIT-A-{suffix}", "source_assignment_ids": assignment_ids[:2]},
            {"output_batch_code": f"SPLIT-B-{suffix}", "source_assignment_ids": assignment_ids[2:]},
        ],
    }
    split_resp = client.post(f"/farms/{farm_id}/crop-batches/{batch['id']}/split", headers=headers, json=split_payload)
    assert split_resp.status_code == 201
    split_event = split_resp.json()
    assert split_event["derivation_kind"] == "split"
    assert len(split_event["sources"]) == 1
    assert len(split_event["outputs"]) == 2
    assert split_event["total_carrier_transfer_count"] == 4
    assert split_event["total_source_plant_count"] == split_event["total_output_plant_count"] == 400

    # 3. Confirm the source is superseded.
    source_after = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}", headers=headers).json()
    assert source_after["state"] == "superseded"
    assert source_after["superseded_by_batch_derivation_event_id"] == split_event["id"]

    # 4. Confirm outputs inherit workflow version and current stage; each has
    # exactly one active destination assignment per transferred carrier.
    output_batches = {o["output_batch"]["code"]: o["output_batch"] for o in split_event["outputs"]}
    for code in (f"SPLIT-A-{suffix}", f"SPLIT-B-{suffix}"):
        output_id = output_batches[code]["id"]
        output_detail = client.get(f"/farms/{farm_id}/crop-batches/{output_id}", headers=headers).json()
        assert output_detail["state"] == "active"
        assert output_detail["workflow_version_id"] == batch["workflow_version_id"]
        assert output_detail["current_stage"]["code"] == "SEEDING"
        assert output_detail["created_by_batch_derivation_event_id"] == split_event["id"]

        history = client.get(f"/farms/{farm_id}/crop-batches/{output_id}/stage-history", headers=headers).json()
        assert len(history) == 1
        assert history[0]["stage"]["code"] == "SEEDING"

        new_assignments = client.get(f"/farms/{farm_id}/crop-batches/{output_id}/carriers", headers=headers).json()
        assert len(new_assignments) == 2
        for a in new_assignments:
            assert a["released_effective_time"] is None
            assert a["opening_batch_derivation_event_id"] == split_event["id"]

    # 5-6. Confirm every source assignment is released.
    old_assignments_after = client.get(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/carriers", headers=headers
    ).json()
    for a in old_assignments_after:
        assert a["released_effective_time"] is not None
        assert a["released_by_batch_derivation_event_id"] == split_event["id"]

    # 13. No configured workflow transition occurred (both outputs are still
    # in SEEDING, matched above via current_stage).

    # 14-15. Retry the split command; confirm no duplicates.
    retry_resp = client.post(f"/farms/{farm_id}/crop-batches/{batch['id']}/split", headers=headers, json=split_payload)
    assert retry_resp.status_code == 201
    assert retry_resp.json()["id"] == split_event["id"]

    # 16. Source rejects a new sowing command.
    extra_carrier = client.post(
        f"/farms/{farm_id}/carriers", headers=headers, json={"carrier_type_code": "seed_tray", "code": f"tray-extra-{suffix}"}
    ).json()
    blocked_resp = client.post(
        f"/farms/{farm_id}/crop-batches/{batch['id']}/sowings", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "lines": [{"carrier_id": extra_carrier["id"], "seed_lot_id": seed_lot["id"], "sown_site_count": 5, "seed_count": 5}],
        },
    )
    assert blocked_resp.status_code == 409

    # 17. Immediate lineage reads correctly for both source and outputs.
    source_lineage = client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/lineage", headers=headers).json()
    assert len(source_lineage["children"]) == 2
    assert all(c["derivation_event_id"] == split_event["id"] for c in source_lineage["children"])
    assert source_lineage["parents"] == []

    split_a_id = output_batches[f"SPLIT-A-{suffix}"]["id"]
    split_b_id = output_batches[f"SPLIT-B-{suffix}"]["id"]
    split_a_lineage = client.get(f"/farms/{farm_id}/crop-batches/{split_a_id}/lineage", headers=headers).json()
    assert len(split_a_lineage["parents"]) == 1
    assert split_a_lineage["parents"][0]["batch"]["id"] == batch["id"]
    assert split_a_lineage["parents"][0]["recorded_plant_quantity_total"] == 200

    # 18. Reject cross-tenant access to the derivation event and lineage.
    from app.services import membership_service, tenant_service, user_service

    tenant_b = tenant_service.create_tenant(db_session, code=f"deriv-tenant-b-{suffix}", name="Tenant B")
    user_b = user_service.create_user(
        db_session, oidc_issuer="iss", oidc_subject=f"deriv-b-{suffix}", email=f"derivb-{suffix}@example.com",
        display_name="B",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant_b.id, user_id=user_b.id, role_code="tenant_admin", actor_user_id=None
    )
    headers_b = {"X-Dev-Tenant-Id": str(tenant_b.id), "X-Dev-User-Id": str(user_b.id)}
    assert client.get(f"/farms/{farm_id}/batch-derivations/{split_event['id']}", headers=headers_b).status_code == 404
    assert client.get(f"/farms/{farm_id}/crop-batches/{batch['id']}/lineage", headers=headers_b).status_code == 404

    # --- Merge acceptance: re-merge the two split outputs into one --------------------

    merge_command_id = str(uuid.uuid4())
    merge_payload = {
        "client_command_id": merge_command_id, "effective_time": _now_iso(),
        "source_batch_ids": [split_a_id, split_b_id], "output_batch_code": f"REMERGED-{suffix}",
    }
    merge_resp = client.post(f"/farms/{farm_id}/crop-batch-merges", headers=headers, json=merge_payload)
    assert merge_resp.status_code == 201
    merge_event = merge_resp.json()
    assert merge_event["derivation_kind"] == "merge"
    assert len(merge_event["sources"]) == 2
    assert len(merge_event["outputs"]) == 1
    assert merge_event["total_output_plant_count"] == 400

    for bid in (split_a_id, split_b_id):
        detail = client.get(f"/farms/{farm_id}/crop-batches/{bid}", headers=headers).json()
        assert detail["state"] == "superseded"
        assert detail["superseded_by_batch_derivation_event_id"] == merge_event["id"]

    merged_id = merge_event["outputs"][0]["output_batch"]["id"]
    merged_detail = client.get(f"/farms/{farm_id}/crop-batches/{merged_id}", headers=headers).json()
    assert merged_detail["state"] == "active"
    assert merged_detail["current_stage"]["code"] == "SEEDING"
    merged_assignments = client.get(f"/farms/{farm_id}/crop-batches/{merged_id}/carriers", headers=headers).json()
    assert len(merged_assignments) == 4

    # Retry the merge command; confirm no duplicates.
    merge_retry = client.post(f"/farms/{farm_id}/crop-batch-merges", headers=headers, json=merge_payload)
    assert merge_retry.status_code == 201
    assert merge_retry.json()["id"] == merge_event["id"]

    merged_lineage = client.get(f"/farms/{farm_id}/crop-batches/{merged_id}/lineage", headers=headers).json()
    assert {p["batch"]["id"] for p in merged_lineage["parents"]} == {split_a_id, split_b_id}


@pytest.mark.integration
def test_merge_incompatible_workflow_versions_rejected(client, active_context) -> None:
    tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Merge Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]

    def _new_batch(code_suffix: str) -> dict:
        crop = client.post(
            "/crops", headers=headers,
            json={"code": f"crop-{code_suffix}", "common_name": "Iceberg", "crop_category": "leafy_green"},
        ).json()
        variety = client.post(
            f"/crops/{crop['id']}/varieties", headers=headers, json={"code": f"var-{code_suffix}", "name": "V"}
        ).json()
        ps = client.post("/production-systems", headers=headers, json={"code": f"ps-{code_suffix}", "name": "PS"}).json()
        workflow = client.post(
            "/workflows", headers=headers,
            json={"crop_id": crop["id"], "variety_id": variety["id"], "production_system_id": ps["id"], "code": f"wf-{code_suffix}", "name": "WF"},
        ).json()
        version = client.post(f"/workflows/{workflow['id']}/versions", headers=headers).json()
        seeding = client.post(
            f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
            json={"code": "SEEDING", "name": "Seeding", "display_order": 0, "stage_category": "seeding", "is_start": True, "is_terminal": False},
        ).json()
        complete = client.post(
            f"/workflows/{workflow['id']}/versions/{version['id']}/stages", headers=headers,
            json={"code": "COMPLETE", "name": "Complete", "display_order": 1, "stage_category": "completed", "is_start": False, "is_terminal": True},
        ).json()
        client.post(
            f"/workflows/{workflow['id']}/versions/{version['id']}/transitions", headers=headers,
            json={"from_stage_id": seeding["id"], "to_stage_id": complete["id"], "code": "ADV", "name": "Adv"},
        )
        client.post(f"/workflows/{workflow['id']}/versions/{version['id']}/publish", headers=headers)
        batch = client.post(
            f"/farms/{farm_id}/crop-batches", headers=headers,
            json={"code": f"BATCH-{code_suffix}", "workflow_id": workflow["id"], "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso()},
        ).json()
        return batch

    batch1 = _new_batch(f"a{suffix}")
    batch2 = _new_batch(f"b{suffix}")

    resp = client.post(
        f"/farms/{farm_id}/crop-batch-merges", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(),
            "source_batch_ids": [batch1["id"], batch2["id"]], "output_batch_code": f"BAD-{suffix}",
        },
    )
    assert resp.status_code == 422
