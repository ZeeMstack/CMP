"""PILOT-SCAN-001: behavioral proof that `app.api.qr`'s dynamic,
entity-type-dependent permission gate actually holds -- the structural
companion to this module's own exemption comments in
`test_authz_read_enforcement_architecture.py`/
`test_authz_mutation_enforcement_architecture.py` (a generic QR resolver
cannot carry one static `Permission` the way the rest of the codebase's
routes do, so this file is what proves it is not silently unauthorized).

`storekeeper` and `operator` are chosen because their permission sets
diverge sharply on exactly the entity types this ticket covers: a
storekeeper holds no `harvest.read`/`crop_batch.read` at all, while an
operator holds `carrier.read`/`crop_batch.read` (needed to scan the floor)
but not `crop_batch.manage`/`carrier.manage` (so it can scan, but not
generate or print, a label) -- see `app/core/permissions.py`'s own
`ROLE_PERMISSIONS`. Builds its scenario directly on the ordinary
`client`/`db_session` fixtures (single shared connection, automatically
rolled back at teardown) -- no `committed_connection`/manual cleanup is
needed here, unlike `test_qr_scan_acceptance.py`, since nothing in this
file needs a second, genuinely separate connection concurrently."""
import uuid
from decimal import Decimal

import pytest

from app.services import membership_service, user_service
from tests._traceability_scenario import build_batch_with_assignments, harvest_all


@pytest.mark.integration
def test_qr_dynamic_permission_gate(client, db_session, active_context_with_farm) -> None:
    tenant, admin_user, admin_headers, farm = active_context_with_farm

    scaffold = build_batch_with_assignments(db_session, tenant, admin_user, farm, carrier_count=1)
    batch_id = scaffold["batch"].id
    carrier_id = scaffold["carriers"][0].id
    assignment_id = scaffold["assignment_ids"][0]
    _, hpl_id = harvest_all(
        db_session, tenant, admin_user, farm, batch_id=batch_id, assignment_ids=[assignment_id],
        weight_per_line=Decimal("5.000"),
    )
    db_session.commit()

    storekeeper_user = user_service.create_user(
        db_session, oidc_issuer="qr-authz", oidc_subject=f"storekeeper-{uuid.uuid4().hex[:8]}",
        email=f"storekeeper-{uuid.uuid4().hex[:8]}@example.com", display_name="Storekeeper",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=storekeeper_user.id, role_code="storekeeper", actor_user_id=None,
    )
    operator_user = user_service.create_user(
        db_session, oidc_issuer="qr-authz", oidc_subject=f"operator-{uuid.uuid4().hex[:8]}",
        email=f"operator-{uuid.uuid4().hex[:8]}@example.com", display_name="Operator",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=operator_user.id, role_code="operator", actor_user_id=None,
    )
    db_session.commit()

    farm_id = farm.id
    storekeeper_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(storekeeper_user.id)}
    operator_headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(operator_user.id)}

    # tenant_admin generates a QR for the Carrier and one for the Harvested
    # Produce Lot.
    resp = client.post(f"/farms/{farm_id}/qr/carrier/{carrier_id}/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    carrier_token = resp.json()["token"]

    resp = client.post(f"/farms/{farm_id}/qr/harvested_produce_lot/{hpl_id}/generate", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    hpl_token = resp.json()["token"]

    # storekeeper: has carrier.read but not harvest.read -- can scan the
    # Carrier, is denied scanning the Harvested Produce Lot.
    resp = client.get(f"/qr/{carrier_token}", headers=storekeeper_headers)
    assert resp.status_code == 200, resp.text
    resp = client.get(f"/qr/{hpl_token}", headers=storekeeper_headers)
    assert resp.status_code == 403, resp.text

    # operator: has carrier.read (can scan) but not carrier.manage (cannot
    # generate/print).
    resp = client.get(f"/qr/{carrier_token}", headers=operator_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/farms/{farm_id}/qr/carrier/{carrier_id}/generate", headers=operator_headers)
    assert resp.status_code == 403, resp.text
    resp = client.post(
        f"/qr/{carrier_token}/print", json={"template": "carrier_small", "template_version": "v1"},
        headers=operator_headers,
    )
    assert resp.status_code == 403, resp.text

    # operator DOES have both harvest.read and harvest.manage (a floor role
    # that records its own Harvest) -- scanning AND generating a label for
    # the Harvested Produce Lot both succeed, unlike the Carrier case above
    # where operator holds only carrier.read. Proves the gate really does
    # vary per entity type, not just a single blanket allow/deny.
    resp = client.get(f"/qr/{hpl_token}", headers=operator_headers)
    assert resp.status_code == 200, resp.text
    resp = client.post(f"/farms/{farm_id}/qr/harvested_produce_lot/{hpl_id}/generate", headers=operator_headers)
    assert resp.status_code == 200, resp.text
