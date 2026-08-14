"""FARM-SETUP-001: HTTP-level tests for the Farm Setup routes -- authorization
(location.manage AND asset.manage for create -- FARM-SETUP-001.1 section 6
-- location.read for the two read endpoints), tenant isolation, and backend
error-mapping to the documented HTTP semantics (404 not-found, 409
duplicate/idempotency conflict, 422 invalid structure)."""
import uuid

import pytest

from app.core import permissions as permissions_module
from app.core.permissions import Permission
from app.schemas.farm_setup import GreenhouseSetupCreate, LeafySetupConfig, SpanSetupConfig, TableGeneratorConfig, ZoneSetupConfig
from app.services import farm_service, farm_setup_service, membership_service, tenant_service, user_service
from tests._traceability_scenario import build_committed_tenant_farm, cleanup_traceability_scenario, committed_connection


def _leafy_setup_payload(code: str, ccid: str | None = None) -> GreenhouseSetupCreate:
    return GreenhouseSetupCreate(
        code=code, name="Leafy GH", classification="leafy_greens", client_command_id=ccid or uuid.uuid4(),
        leafy=LeafySetupConfig(zones=[
            ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(code="S01", tables=TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2, capacity=24))
            ])
        ]),
    )


def _leafy_body(code: str, ccid: str | None = None) -> dict:
    return {
        "code": code,
        "name": "Leafy GH",
        "classification": "leafy_greens",
        "client_command_id": ccid or str(uuid.uuid4()),
        "leafy": {
            "zones": [
                {
                    "code": "Z01",
                    "spans": [
                        {"code": "S01", "tables": {"code_prefix": "T", "start": 1, "end": 2, "pad_width": 2, "capacity": 24}}
                    ],
                }
            ]
        },
    }


@pytest.mark.integration
def test_create_greenhouse_setup_success(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    resp = client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-API1"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "GH-API1"
    assert body["counts"]["zones"] == 1
    assert body["counts"]["tables"] == 2


@pytest.mark.integration
def test_create_greenhouse_setup_requires_location_manage(client, db_session) -> None:
    """storekeeper holds location.read but not location.manage."""
    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db_session, code=f"fs-authz-{suffix}", name="FS Authz Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="fs-authz", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="FS Authz",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="storekeeper", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    headers = {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}
    db_session.commit()

    resp = client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-DENIED"))
    assert resp.status_code == 403


def _hypothetical_role_headers(db_session, *, suffix: str) -> tuple[dict[str, str], uuid.UUID]:
    """FARM-SETUP-001.1 section 6: like `test_authz_observation_permission_
    split_http.py`'s own established pattern -- a real, DB-approved
    role_code (`storekeeper`, chosen because its own real grant has
    neither location.manage nor asset.manage, so this patch introduces no
    accidental overlap) with its `_ROLE_PERMISSIONS` entry temporarily
    monkeypatched to a hypothetical grant that does not exist in the
    current policy. Exercises the real FastAPI dependency chain end to
    end -- not a synthetic identity, not a route-level mock."""
    tenant = tenant_service.create_tenant(db_session, code=f"fs-assetgap-{suffix}", name="FS Asset Gap Tenant")
    user = user_service.create_user(
        db_session, oidc_issuer="fs-assetgap", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="FS Asset Gap",
    )
    membership_service.add_membership(db_session, tenant_id=tenant.id, user_id=user.id, role_code="storekeeper", actor_user_id=None)
    farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-{suffix}", name="Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    db_session.commit()
    return {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}, farm.id


@pytest.mark.integration
def test_create_greenhouse_setup_requires_asset_manage_even_with_location_manage(client, db_session, monkeypatch) -> None:
    """FARM-SETUP-001.1 section 6: this command can register Assets
    (Nursery trolleys/seeding machines), so it must not rely on the
    incidental fact that every role currently holding location.manage also
    holds asset.manage. A hypothetical membership granted ONLY
    location.manage (never a real role under the current policy) must
    still be denied -- proving the route genuinely enforces asset.manage,
    not merely documents an assumption about it."""
    monkeypatch.setitem(
        permissions_module._ROLE_PERMISSIONS, "storekeeper",
        frozenset({Permission.LOCATION_MANAGE, Permission.LOCATION_READ, Permission.FARM_READ}),
    )
    headers, farm_id = _hypothetical_role_headers(db_session, suffix=uuid.uuid4().hex[:8])
    resp = client.post(f"/farms/{farm_id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-ASSETGAP-1"))
    assert resp.status_code == 403


@pytest.mark.integration
def test_create_greenhouse_setup_requires_location_manage_even_with_asset_manage(client, db_session, monkeypatch) -> None:
    """The inverse gap: a hypothetical membership granted ONLY
    asset.manage (never location.manage) must also be denied."""
    monkeypatch.setitem(
        permissions_module._ROLE_PERMISSIONS, "storekeeper",
        frozenset({Permission.ASSET_MANAGE, Permission.LOCATION_READ, Permission.FARM_READ}),
    )
    headers, farm_id = _hypothetical_role_headers(db_session, suffix=uuid.uuid4().hex[:8])
    resp = client.post(f"/farms/{farm_id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-ASSETGAP-2"))
    assert resp.status_code == 403


@pytest.mark.integration
def test_create_greenhouse_setup_succeeds_with_both_location_and_asset_manage(client, db_session, monkeypatch) -> None:
    """Sanity check on the monkeypatch mechanism itself: granting BOTH
    permissions to the same hypothetical role succeeds -- proving the two
    403s above are a genuine, isolated permission gap rather than an
    unrelated route bug that would 403 regardless of grant."""
    monkeypatch.setitem(
        permissions_module._ROLE_PERMISSIONS, "storekeeper",
        frozenset({Permission.LOCATION_MANAGE, Permission.ASSET_MANAGE, Permission.LOCATION_READ, Permission.FARM_READ}),
    )
    headers, farm_id = _hypothetical_role_headers(db_session, suffix=uuid.uuid4().hex[:8])
    resp = client.post(f"/farms/{farm_id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-ASSETGAP-3"))
    assert resp.status_code == 201, resp.text


@pytest.mark.integration
def test_create_greenhouse_setup_duplicate_code_maps_to_409(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-API2"))
    resp = client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-API2"))
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


@pytest.mark.integration
def test_create_greenhouse_setup_replay_with_different_payload_maps_to_409(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    ccid = str(uuid.uuid4())
    client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-API3", ccid=ccid))
    resp = client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=_leafy_body("GH-API3-X", ccid=ccid))
    assert resp.status_code == 409


@pytest.mark.integration
def test_create_greenhouse_setup_invalid_payload_maps_to_422(client, active_context_with_farm) -> None:
    _tenant, _user, headers, farm = active_context_with_farm
    body = _leafy_body("GH-API4")
    body["leafy"]["zones"][0]["spans"][0]["tables"]["capacity"] = 0
    resp = client.post(f"/farms/{farm.id}/farm-setup/greenhouses", headers=headers, json=body)
    assert resp.status_code == 422


@pytest.mark.integration
def test_overview_and_structure_read_require_location_read(client, test_engine) -> None:
    """The two read routes (`GET .../farm-setup/greenhouses`,
    `GET .../farm-setup/greenhouses/{id}`) depend on `get_engine`
    (`_snapshot_connection`, a genuinely separate connection from the
    request-scoped `db_session`) -- their test data must be committed on a
    real, independent connection (`committed_connection`), not built via
    the rollback-only `db_session` fixture, or the read would only ever
    see an empty/absent farm regardless of what it's actually testing."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session, suffix=f"fs-read-{uuid.uuid4().hex[:8]}")
            tenant_id, user_id, farm_id = tenant.id, user.id, farm.id
            result = farm_setup_service.create_greenhouse_setup(
                session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
                payload=_leafy_setup_payload("GH-API5"),
            )
            greenhouse_id = result.greenhouse_id
            session.commit()
        headers = {"X-Dev-Tenant-Id": str(tenant_id), "X-Dev-User-Id": str(user_id)}

        overview = client.get(f"/farms/{farm_id}/farm-setup/greenhouses", headers=headers)
        assert overview.status_code == 200
        codes = {item["code"] for item in overview.json()}
        assert "GH-API5" in codes

        structure = client.get(f"/farms/{farm_id}/farm-setup/greenhouses/{greenhouse_id}", headers=headers)
        assert structure.status_code == 200
        assert structure.json()["classification"] == "leafy_greens"
        assert len(structure.json()["leafy_zones"]) == 1
    finally:
        if tenant_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_cross_tenant_structure_read_is_404(client, test_engine) -> None:
    tenant_a_id = tenant_b_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant_a, user_a, farm_a = build_committed_tenant_farm(session, suffix=f"fs-cross-a-{uuid.uuid4().hex[:8]}")
            tenant_a_id, farm_a_id = tenant_a.id, farm_a.id
            result = farm_setup_service.create_greenhouse_setup(
                session, tenant_id=tenant_a.id, farm_id=farm_a.id, actor_user_id=user_a.id,
                payload=_leafy_setup_payload("GH-CROSSAPI"),
            )
            greenhouse_id = result.greenhouse_id
            session.commit()

        with committed_connection(test_engine) as session:
            tenant_b, user_b, _farm_b = build_committed_tenant_farm(session, suffix=f"fs-cross-b-{uuid.uuid4().hex[:8]}")
            tenant_b_id, user_b_id = tenant_b.id, user_b.id
            session.commit()

        headers_b = {"X-Dev-Tenant-Id": str(tenant_b_id), "X-Dev-User-Id": str(user_b_id)}

        resp = client.get(f"/farms/{farm_a_id}/farm-setup/greenhouses/{greenhouse_id}", headers=headers_b)
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not found"}

        resp2 = client.get(f"/farms/{farm_a_id}/farm-setup/greenhouses", headers=headers_b)
        assert resp2.status_code == 404
    finally:
        if tenant_a_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_a_id)
        if tenant_b_id is not None:
            cleanup_traceability_scenario(test_engine, tenant_b_id)
