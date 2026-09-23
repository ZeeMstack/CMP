"""UX-OPS-001D0: End Delivery command (N07) and the exact, half-open water
exposure interval engine (N06). Real concurrency and migration proofs live
in test_water_delivery_end_concurrency.py / test_water_delivery_end_migration.py.

Several exposure tests are regressions against the PILOT-WATER-001A service,
which labelled the WHOLE window `RECORDED_DELIVERY_EXPOSURE` whenever any
delivery on the Circuit overlapped it, and aggregated reservoirs/Locations
across non-overlapping evidence."""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_event import AuditEvent
from app.models.water_delivery_end_event import WaterDeliveryEndEvent
from app.services import (
    farm_service,
    membership_service,
    reservoir_operations_service,
    tenant_service,
    user_service,
    water_exposure_service,
    water_topology_service,
)
from app.services.errors import (
    WaterDeliveryEndCommandConflictError,
    WaterDeliveryEndValidationError,
    WaterDeliveryEventAlreadyEndedError,
    WaterDeliveryEventNotFoundError,
)
from tests._operational_read_scenario import (
    batch_id_by_code,
    build_direct_placement_workflow_scaffold,
    build_greenhouse_tree,
    place_carrier,
    sow_batch,
    split,
)

REC = water_exposure_service.RECORDED_DELIVERY
TOPO = water_exposure_service.CONFIGURED_TOPOLOGY
FORBIDDEN_WORDS = ("affected", "contaminated", "infected", "infection", "disease", "contamination")


@pytest.fixture(autouse=True)
def _dev_auth_enabled(monkeypatch):
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)


def _t0() -> datetime:
    """A fixed, past, minute-aligned anchor so every offset below stays in
    the past (future timestamps are rejected by the recording commands)."""
    return (datetime.now(timezone.utc) - timedelta(days=10)).replace(second=0, microsecond=0)


def _m(t0: datetime, minutes: int) -> datetime:
    return t0 + timedelta(minutes=minutes)


def _register_reservoir(db, tenant, user, farm, code):
    return water_topology_service.register_reservoir(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=code, name="Reservoir",
        reservoir_type="nutrient_reservoir", nominal_capacity=None, nominal_capacity_uom_id=None,
        linked_asset_id=None, location_id=None, notes=None,
    )


def _record_delivery(db, tenant, user, farm, *, reservoir_id, circuit_id, start, end):
    return reservoir_operations_service.record_delivery_event(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_id,
        irrigation_circuit_id=circuit_id, effective_start=start, effective_end=end, delivered_volume=None,
        delivered_volume_uom_id=None, nutrient_mix_id=None, notes=None, client_command_id=uuid.uuid4(),
    )


def _end(db, tenant, user, farm, delivery_id, effective_end, *, note=None, client_command_id=None):
    return reservoir_operations_service.end_delivery_event(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, water_delivery_event_id=delivery_id,
        effective_end=effective_end, note=note, client_command_id=client_command_id or uuid.uuid4(),
    )


def _scenario(db, tenant, user, farm, t0, *, cdl_from=None, rcl_from=None, carrier_count=1, sow_at=None,
              place_at=None):
    """Greenhouse -> Zone -> Span -> 2 Grow Tables. One Batch whose Carrier
    occupies Grow Table 1. Reservoir A -> Circuit -> Delivery Point mapped to
    the ZONE (so Grow Table 1 is served through descendant expansion). All
    history starts well before `t0` unless overridden."""
    suffix = uuid.uuid4().hex[:8]
    tree = build_greenhouse_tree(db, tenant, user, farm, suffix=suffix, position_count=2)
    scaffold = build_direct_placement_workflow_scaffold(db, tenant, user, farm, suffix=suffix)
    sow_at = sow_at or t0 - timedelta(days=2)
    sown = sow_batch(
        db, tenant, user, farm, scaffold, effective_time=sow_at, code_suffix=suffix,
        carrier_type_code="cultivation_plate", carrier_count=carrier_count,
    )
    for index, carrier in enumerate(sown["trays"]):
        place_carrier(
            db, tenant, user, farm, carrier_id=carrier.id, location_id=tree["positions"][index].id,
            effective_time=place_at or sow_at,
        )
    reservoir = _register_reservoir(db, tenant, user, farm, f"RES-A-{suffix}")
    circuit = water_topology_service.register_irrigation_circuit(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"IC-{suffix}", name="Circuit",
        system_type="dwc", notes=None,
    )
    rcl = water_topology_service.open_reservoir_circuit_link(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        irrigation_circuit_id=circuit.id, effective_from=rcl_from or t0 - timedelta(days=3), reason=None,
    )
    delivery_point = water_topology_service.register_water_delivery_point(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"DP-{suffix}", name="Zone DP",
        location_id=tree["zone"].id, notes=None,
    )
    cdl = water_topology_service.open_circuit_delivery_point_link(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, irrigation_circuit_id=circuit.id,
        water_delivery_point_id=delivery_point.id, effective_from=cdl_from or t0 - timedelta(days=3), reason=None,
    )
    return {
        "suffix": suffix, "tree": tree, "batch": sown["batch"], "carrier": sown["tray"], "carriers": sown["trays"],
        "assignment_ids": sown["assignment_ids"], "reservoir": reservoir, "circuit": circuit, "rcl": rcl,
        "cdl": cdl, "delivery_point": delivery_point,
    }


def _circuit_intervals(db, tenant, farm, s, t0, start, end):
    return water_exposure_service.get_circuit_water_exposure_timeline(
        db, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=s["circuit"].id,
        window_start=_m(t0, start), window_end=_m(t0, end),
    )["intervals"]


def _batch_timeline(db, tenant, farm, batch_id, t0, start, end):
    return water_exposure_service.get_batch_water_exposure_timeline(
        db, tenant_id=tenant.id, farm_id=farm.id, batch_id=batch_id, window_start=_m(t0, start),
        window_end=_m(t0, end),
    )


def _shape(intervals, t0):
    """(kind, start-minute, end-minute) relative to t0."""
    return [
        (i["exposure_kind"], int((i["interval_start"] - t0).total_seconds() // 60),
         int((i["interval_end"] - t0).total_seconds() // 60))
        for i in intervals
    ]


def _gap_shape(gaps, t0):
    return [
        (g["reason"], int((g["gap_start"] - t0).total_seconds() // 60), int((g["gap_end"] - t0).total_seconds() // 60))
        for g in gaps
    ]


def _fact(interval: dict) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in interval.items()))


def _other_tenant_headers(db):
    suffix = uuid.uuid4().hex[:8]
    tenant = tenant_service.create_tenant(db, code=f"other-{suffix}", name="Other Tenant")
    user = user_service.create_user(
        db, oidc_issuer="other", oidc_subject=suffix, email=f"other-{suffix}@example.com", display_name="Other",
    )
    membership_service.add_membership(db, tenant_id=tenant.id, user_id=user.id, role_code="tenant_admin", actor_user_id=None)
    return tenant, {"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(user.id)}


def _open_delivery(db, tenant, user, farm, t0=None):
    t0 = t0 or _t0()
    suffix = uuid.uuid4().hex[:8]
    reservoir = _register_reservoir(db, tenant, user, farm, f"RES-{suffix}")
    circuit = water_topology_service.register_irrigation_circuit(
        db, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"IC-{suffix}", name="Circuit",
        system_type="dwc", notes=None,
    )
    delivery = _record_delivery(
        db, tenant, user, farm, reservoir_id=reservoir.id, circuit_id=circuit.id, start=t0, end=None,
    )
    return delivery, circuit, t0


def _raw_delivery_row(db, delivery_id) -> dict:
    return db.execute(
        text("SELECT to_jsonb(d) FROM water_delivery_events d WHERE id = :id"), {"id": delivery_id}
    ).scalar_one()


def _ended_audit_count(db, tenant_id, delivery_id) -> int:
    return len(
        db.execute(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.entity_id == delivery_id,
                AuditEvent.action == "water_delivery_event.ended",
            )
        ).scalars().all()
    )


def _end_row_count(db, delivery_id) -> int:
    return len(
        db.execute(
            select(WaterDeliveryEndEvent).where(WaterDeliveryEndEvent.water_delivery_event_id == delivery_id)
        ).scalars().all()
    )


# =====================================================================================
# End Delivery (N07)
# =====================================================================================


def test_end_open_delivery_resolves_end_in_every_delivery_read(active_context_with_farm, db_session, client):
    """End proof 1. After the End Delivery command, the farm list, circuit
    list, and detail reads (service and HTTP) all return the resolved end."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    before = reservoir_operations_service.get_delivery_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, water_delivery_event_id=delivery.id
    )
    assert before.effective_end is None and before.end_source is None

    response = client.post(
        f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end", headers=headers,
        json={"effective_end": _m(t0, 25).isoformat(), "note": "pump stopped", "client_command_id": str(uuid.uuid4())},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert datetime.fromisoformat(body["effective_end"]) == _m(t0, 25)
    assert body["end_source"] == "END_EVENT"
    assert body["end_note"] == "pump stopped"
    assert body["water_delivery_end_event_id"]

    for path in (
        f"/farms/{farm.id}/water-delivery-events",
        f"/irrigation-circuits/{circuit.id}/water-delivery-events",
    ):
        listed = [d for d in client.get(path, headers=headers).json() if d["id"] == str(delivery.id)]
        assert len(listed) == 1
        assert datetime.fromisoformat(listed[0]["effective_end"]) == _m(t0, 25)
        assert listed[0]["end_source"] == "END_EVENT"
    detail = client.get(f"/farms/{farm.id}/water-delivery-events/{delivery.id}", headers=headers)
    assert detail.status_code == 200
    assert datetime.fromisoformat(detail.json()["effective_end"]) == _m(t0, 25)

    # A delivery created WITH an end resolves from its own original end,
    # with no end-event row.
    closed = _record_delivery(
        db_session, tenant, user, farm, reservoir_id=delivery.reservoir_id, circuit_id=circuit.id,
        start=_m(t0, 30), end=_m(t0, 40),
    )
    resolved = reservoir_operations_service.get_delivery_event(
        db_session, tenant_id=tenant.id, farm_id=farm.id, water_delivery_event_id=closed.id
    )
    assert resolved.effective_end == _m(t0, 40)
    assert resolved.end_source == "RECORDED_AT_CREATION"
    assert resolved.water_delivery_end_event_id is None
    assert _end_row_count(db_session, closed.id) == 0


def test_end_never_modifies_the_original_delivery_row(active_context_with_farm, db_session):
    """End proof 2. The original `water_delivery_events` row is byte-for-byte
    unchanged after closure (still `effective_end = NULL` on disk)."""
    tenant, user, _headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    before = _raw_delivery_row(db_session, delivery.id)
    _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    after = _raw_delivery_row(db_session, delivery.id)
    assert after == before
    assert after["effective_end"] is None


def test_end_same_command_same_payload_replays_one_success(active_context_with_farm, db_session, client):
    """End proof 3. Same command id + same payload (including the same
    instant expressed in another UTC offset) replays: one end row, one
    audit record, same response."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    first = _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10), note="done", client_command_id=command_id)
    same_instant_other_offset = _m(t0, 10).astimezone(timezone(timedelta(hours=4)))
    second = _end(
        db_session, tenant, user, farm, delivery.id, same_instant_other_offset, note="done",
        client_command_id=command_id,
    )
    assert first == second
    http = client.post(
        f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end", headers=headers,
        json={"effective_end": _m(t0, 10).isoformat(), "note": "done", "client_command_id": str(command_id)},
    )
    assert http.status_code == 201
    assert http.json()["water_delivery_end_event_id"] == str(first.water_delivery_end_event_id)
    assert _end_row_count(db_session, delivery.id) == 1
    assert _ended_audit_count(db_session, tenant.id, delivery.id) == 1


@pytest.mark.parametrize(
    "changed", [{"minutes": 11}, {"note": "different"}, {"note": None}, {"note": ""}],
)
def test_end_same_command_different_payload_conflicts(active_context_with_farm, db_session, client, changed):
    """End proof 4. Reusing a command id with a different end time or note
    (a missing note and an empty note are different payloads) is a
    deterministic 409, with no second row."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    command_id = uuid.uuid4()
    _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10), note="original", client_command_id=command_id)
    with pytest.raises(WaterDeliveryEndCommandConflictError):
        _end(
            db_session, tenant, user, farm, delivery.id, _m(t0, changed.get("minutes", 10)),
            note=changed.get("note", "original"), client_command_id=command_id,
        )
    http = client.post(
        f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end", headers=headers,
        json={
            "effective_end": _m(t0, changed.get("minutes", 10)).isoformat(), "note": changed.get("note", "original"),
            "client_command_id": str(command_id),
        },
    )
    assert http.status_code == 409
    assert _end_row_count(db_session, delivery.id) == 1


def test_end_second_command_cannot_close_an_already_closed_delivery(active_context_with_farm, db_session, client):
    """End proof 5 (sequential half; the real race is in
    test_water_delivery_end_concurrency.py)."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    with pytest.raises(WaterDeliveryEventAlreadyEndedError):
        _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    http = client.post(
        f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end", headers=headers,
        json={"effective_end": _m(t0, 20).isoformat(), "client_command_id": str(uuid.uuid4())},
    )
    assert http.status_code == 409
    assert _end_row_count(db_session, delivery.id) == 1


def test_end_second_end_row_rejected_by_database_uniqueness(active_context_with_farm, db_session):
    """End proof 5 (database half): even bypassing the service, a second end
    event for the same delivery is rejected by
    `ux_water_delivery_end_events_delivery`."""
    tenant, user, _headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    with pytest.raises(DBAPIError, match="ux_water_delivery_end_events_delivery"):
        db_session.execute(
            WaterDeliveryEndEvent.__table__.insert().values(
                id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, water_delivery_event_id=delivery.id,
                effective_end=_m(t0, 20), recorded_by_user_id=user.id, client_command_id=uuid.uuid4(),
                request_fingerprint="x",
            )
        )
    db_session.rollback()


def test_end_delivery_created_with_an_end_cannot_be_ended(active_context_with_farm, db_session, client):
    """End proof 6. Service (409) and database trigger both refuse."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    closed = _record_delivery(
        db_session, tenant, user, farm, reservoir_id=delivery.reservoir_id, circuit_id=circuit.id,
        start=_m(t0, 30), end=_m(t0, 40),
    )
    with pytest.raises(WaterDeliveryEventAlreadyEndedError):
        _end(db_session, tenant, user, farm, closed.id, _m(t0, 50))
    http = client.post(
        f"/farms/{farm.id}/water-delivery-events/{closed.id}/end", headers=headers,
        json={"effective_end": _m(t0, 50).isoformat(), "client_command_id": str(uuid.uuid4())},
    )
    assert http.status_code == 409
    with pytest.raises(DBAPIError, match="was recorded with an effective_end"):
        db_session.execute(
            WaterDeliveryEndEvent.__table__.insert().values(
                id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, water_delivery_event_id=closed.id,
                effective_end=_m(t0, 50), recorded_by_user_id=user.id, client_command_id=uuid.uuid4(),
                request_fingerprint="x",
            )
        )
    db_session.rollback()


def test_end_before_start_and_future_end_are_rejected(active_context_with_farm, db_session, client):
    """End proof 7. End-before-start and a future end are 422 (service),
    end-before-start is also refused by the database trigger, and a naive
    timestamp is rejected at the API boundary. Nothing is written."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    with pytest.raises(WaterDeliveryEndValidationError):
        _end(db_session, tenant, user, farm, delivery.id, _m(t0, -1))
    with pytest.raises(WaterDeliveryEndValidationError):
        _end(db_session, tenant, user, farm, delivery.id, datetime.now(timezone.utc) + timedelta(hours=1))
    path = f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end"
    for effective_end in (_m(t0, -1).isoformat(), (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                          _m(t0, 5).replace(tzinfo=None).isoformat()):
        response = client.post(
            path, headers=headers, json={"effective_end": effective_end, "client_command_id": str(uuid.uuid4())}
        )
        assert response.status_code == 422, response.text
    with pytest.raises(DBAPIError, match="is before delivery"):
        db_session.execute(
            WaterDeliveryEndEvent.__table__.insert().values(
                id=uuid.uuid4(), tenant_id=tenant.id, farm_id=farm.id, water_delivery_event_id=delivery.id,
                effective_end=_m(t0, -1), recorded_by_user_id=user.id, client_command_id=uuid.uuid4(),
                request_fingerprint="x",
            )
        )
    db_session.rollback()
    assert _end_row_count(db_session, delivery.id) == 0
    # effective_end == effective_start is permitted (`>=`).
    resolved = _end(db_session, tenant, user, farm, delivery.id, t0)
    assert resolved.effective_end == t0


def test_end_missing_cross_tenant_and_cross_farm_targets_do_not_leak(active_context_with_farm, db_session, client):
    """End proof 8. Missing, cross-farm, and cross-tenant targets all give
    the same 404 and write nothing; the database FK also refuses an end
    event whose tenant/farm differs from its delivery's."""
    tenant, user, headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"f2-{uuid.uuid4().hex[:6]}", name="Farm 2",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    other_tenant, other_headers = _other_tenant_headers(db_session)
    body = {"effective_end": _m(t0, 10).isoformat(), "client_command_id": str(uuid.uuid4())}

    responses = [
        client.post(f"/farms/{farm.id}/water-delivery-events/{uuid.uuid4()}/end", headers=headers, json=body),
        client.post(f"/farms/{other_farm.id}/water-delivery-events/{delivery.id}/end", headers=headers, json=body),
        client.post(f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end", headers=other_headers, json=body),
        client.get(f"/farms/{other_farm.id}/water-delivery-events/{delivery.id}", headers=headers),
        client.get(f"/farms/{farm.id}/water-delivery-events/{delivery.id}", headers=other_headers),
    ]
    statuses = [r.status_code for r in responses]
    # The cross-tenant farm path is refused at farm access (404/403 without
    # revealing the delivery); every same-tenant miss is the same 404.
    assert statuses[0] == statuses[1] == statuses[3] == 404
    assert statuses[2] in (403, 404) and statuses[4] in (403, 404)
    assert len({r.json()["detail"] for r in (responses[0], responses[1], responses[3])}) == 1
    with pytest.raises(WaterDeliveryEventNotFoundError):
        _end(db_session, other_tenant, user, farm, delivery.id, _m(t0, 10))
    with pytest.raises(WaterDeliveryEventNotFoundError):
        _end(db_session, tenant, user, other_farm, delivery.id, _m(t0, 10))
    assert _end_row_count(db_session, delivery.id) == 0
    assert _raw_delivery_row(db_session, delivery.id)["effective_end"] is None

    with pytest.raises(DBAPIError):
        db_session.execute(
            WaterDeliveryEndEvent.__table__.insert().values(
                id=uuid.uuid4(), tenant_id=tenant.id, farm_id=other_farm.id, water_delivery_event_id=delivery.id,
                effective_end=_m(t0, 10), recorded_by_user_id=user.id, client_command_id=uuid.uuid4(),
                request_fingerprint="x",
            )
        )
    db_session.rollback()


def test_end_event_and_audit_roll_back_together(active_context_with_farm, db_session, monkeypatch):
    """End proof 9. If appending the audit event fails, the end event is
    not committed either."""
    tenant, user, _headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)

    def _fail(*_args, **_kwargs):
        raise RuntimeError("audit store unavailable")

    monkeypatch.setattr(reservoir_operations_service, "append_audit_event", _fail)
    with pytest.raises(RuntimeError, match="audit store unavailable"):
        _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    db_session.rollback()
    assert _end_row_count(db_session, delivery.id) == 0
    assert _ended_audit_count(db_session, tenant.id, delivery.id) == 0
    monkeypatch.undo()
    resolved = _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    assert resolved.effective_end == _m(t0, 10)
    assert _end_row_count(db_session, delivery.id) == 1
    assert _ended_audit_count(db_session, tenant.id, delivery.id) == 1


def test_end_event_history_is_immutable(active_context_with_farm, db_session):
    """End proof 10. Direct UPDATE/DELETE on the end-event ledger is
    rejected by the database."""
    tenant, user, _headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    resolved = _end(db_session, tenant, user, farm, delivery.id, _m(t0, 10))
    table = WaterDeliveryEndEvent.__table__
    with pytest.raises(DBAPIError):
        db_session.execute(
            table.update().where(table.c.id == resolved.water_delivery_end_event_id).values(effective_end=_m(t0, 20))
        )
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(table.delete().where(table.c.id == resolved.water_delivery_end_event_id))
    db_session.rollback()


def test_end_command_requires_nutrient_operations_manage(active_context_with_farm, db_session, client):
    """The End Delivery command reuses `nutrient_operations.manage`: a
    read-only member gets 403 and nothing is written."""
    tenant, user, _headers, farm = active_context_with_farm
    delivery, _circuit, t0 = _open_delivery(db_session, tenant, user, farm)
    reader = user_service.create_user(
        db_session, oidc_issuer="ro", oidc_subject=uuid.uuid4().hex, email=f"{uuid.uuid4().hex}@example.com",
        display_name="Reader",
    )
    membership_service.add_membership(
        db_session, tenant_id=tenant.id, user_id=reader.id, role_code="read_only", actor_user_id=None
    )
    response = client.post(
        f"/farms/{farm.id}/water-delivery-events/{delivery.id}/end",
        headers={"X-Dev-Tenant-Id": str(tenant.id), "X-Dev-User-Id": str(reader.id)},
        json={"effective_end": _m(t0, 10).isoformat(), "client_command_id": str(uuid.uuid4())},
    )
    assert response.status_code == 403
    assert _end_row_count(db_session, delivery.id) == 0


# =====================================================================================
# Exact exposure intervals (N06)
# =====================================================================================


def test_interval_helpers_are_half_open():
    t0 = _t0()
    intersect = water_exposure_service._intersect
    subtract = water_exposure_service._subtract
    assert intersect(_m(t0, 0), _m(t0, 10), (_m(t0, 10), None)) is None  # touching -> empty
    assert intersect(_m(t0, 0), _m(t0, 10), (_m(t0, 5), _m(t0, 5))) is None  # zero-duration -> empty
    assert intersect(_m(t0, 0), _m(t0, 10), (_m(t0, 5), None)) == (_m(t0, 5), _m(t0, 10))
    base = (_m(t0, 0), _m(t0, 60))
    assert subtract(base, [(_m(t0, 20), _m(t0, 30)), (_m(t0, 30), _m(t0, 40))]) == [
        (_m(t0, 0), _m(t0, 20)), (_m(t0, 40), _m(t0, 60)),
    ]
    assert subtract(base, [(_m(t0, 0), _m(t0, 60))]) == []
    assert subtract(base, [(_m(t0, 10), _m(t0, 30)), (_m(t0, 20), _m(t0, 25))]) == [
        (_m(t0, 0), _m(t0, 10)), (_m(t0, 30), _m(t0, 60)),
    ]


def test_ten_minute_delivery_is_ten_minutes_of_recorded_exposure_only(active_context_with_farm, db_session):
    """Exposure proof 1 (regression: 001A upgraded the whole hour)."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    delivery = _record_delivery(
        db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
        start=_m(t0, 20), end=_m(t0, 30),
    )
    intervals = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    assert _shape(intervals, t0) == [(TOPO, 0, 20), (REC, 20, 30), (TOPO, 30, 60)]
    assert intervals[1]["water_delivery_event_id"] == delivery.id
    assert {i["location_id"] for i in intervals} == {s["tree"]["positions"][0].id}
    assert {i["delivery_point_location_id"] for i in intervals} == {s["tree"]["zone"].id}

    legacy = water_exposure_service.get_potentially_exposed_placements_for_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, irrigation_circuit_id=s["circuit"].id,
        window_start=_m(t0, 0), window_end=_m(t0, 60),
    )
    assert [(r["exposure_kind"], r["overlap_start"], r["overlap_end"]) for r in legacy] == [
        (TOPO, _m(t0, 0), _m(t0, 20)), (REC, _m(t0, 20), _m(t0, 30)), (TOPO, _m(t0, 30), _m(t0, 60)),
    ]
    legacy_batch = water_exposure_service.get_water_exposure_history_for_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, window_start=_m(t0, 0),
        window_end=_m(t0, 60),
    )
    assert [r["exposure_kind"] for r in legacy_batch] == [TOPO, REC, TOPO]
    assert all(r["reservoir_ids"] == [s["reservoir"].id] for r in legacy_batch)
    assert all(len(r["location_ids"]) == 1 for r in legacy_batch)


def test_two_non_contiguous_deliveries_stay_two_recorded_intervals(active_context_with_farm, db_session):
    """Exposure proof 2."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    for start, end in ((5, 10), (40, 45)):
        _record_delivery(
            db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
            start=_m(t0, start), end=_m(t0, end),
        )
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 0, 60), t0) == [
        (TOPO, 0, 5), (REC, 5, 10), (TOPO, 10, 40), (REC, 40, 45), (TOPO, 45, 60),
    ]


def test_touching_boundaries_do_not_overlap_and_no_zero_duration_segment(active_context_with_farm, db_session):
    """Exposure proof 3."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    for start, end in ((10, 20), (20, 30), (50, 50)):  # adjacent pair + zero-duration delivery
        _record_delivery(
            db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
            start=_m(t0, start), end=_m(t0, end),
        )
    # A window ending exactly where a delivery starts / starting exactly
    # where one ends does not include it.
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 0, 10), t0) == [(TOPO, 0, 10)]
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 30, 40), t0) == [(TOPO, 30, 40)]
    # Adjacent deliveries: two recorded intervals, no zero-length topology between.
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 10, 30), t0) == [(REC, 10, 20), (REC, 20, 30)]
    # A zero-duration delivery produces no recorded interval and no split.
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 45, 55), t0) == [(TOPO, 45, 55)]
    everything = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    assert all(i["interval_start"] < i["interval_end"] for i in everything)


def test_occupancy_boundary_clips_and_leaves_a_gap_at_an_unserved_location(active_context_with_farm, db_session):
    """Exposure proofs 4 (occupancy) + 9 (gap at an unserved Location)."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    unserved = build_greenhouse_tree(db_session, tenant, user, farm, suffix=s["suffix"] + "-x", position_count=1)
    place_carrier(
        db_session, tenant, user, farm, carrier_id=s["carrier"].id, location_id=unserved["positions"][0].id,
        effective_time=_m(t0, 40),
    )
    timeline = _batch_timeline(db_session, tenant, farm, s["batch"].id, t0, 0, 60)
    assert _shape(timeline["intervals"], t0) == [(TOPO, 0, 40)]
    assert _gap_shape(timeline["gaps"], t0) == [("NO_COMPLETE_TOPOLOGY_ROUTE", 40, 60)]
    assert timeline["gaps"][0]["location_id"] == unserved["positions"][0].id


def test_circuit_delivery_point_link_boundary_clips_and_leaves_a_gap(active_context_with_farm, db_session):
    """Exposure proofs 4 (circuit->delivery-point link) + 9."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0, cdl_from=_m(t0, 20))
    water_topology_service.close_circuit_delivery_point_link(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=s["cdl"].id, effective_to=_m(t0, 45),
    )
    _record_delivery(
        db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
        start=_m(t0, 0), end=_m(t0, 60),
    )
    timeline = _batch_timeline(db_session, tenant, farm, s["batch"].id, t0, 0, 60)
    # The delivery spans the whole hour but is evidence only while the
    # route to this Location is complete.
    assert _shape(timeline["intervals"], t0) == [(REC, 20, 45)]
    assert _gap_shape(timeline["gaps"], t0) == [
        ("NO_COMPLETE_TOPOLOGY_ROUTE", 0, 20), ("NO_COMPLETE_TOPOLOGY_ROUTE", 45, 60),
    ]


def test_reservoir_circuit_link_boundary_clips(active_context_with_farm, db_session):
    """Exposure proof 4 (reservoir->circuit link)."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0, rcl_from=_m(t0, 15))
    water_topology_service.close_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=s["rcl"].id, effective_to=_m(t0, 35),
    )
    timeline = _batch_timeline(db_session, tenant, farm, s["batch"].id, t0, 0, 60)
    assert _shape(timeline["intervals"], t0) == [(TOPO, 15, 35)]
    assert _gap_shape(timeline["gaps"], t0) == [
        ("NO_COMPLETE_TOPOLOGY_ROUTE", 0, 15), ("NO_COMPLETE_TOPOLOGY_ROUTE", 35, 60),
    ]


def test_assignment_boundaries_clip(active_context_with_farm, db_session):
    """Exposure proof 4 (Batch-to-Carrier assignment): the Carrier occupies
    the Table before the Batch is sown onto it, and a split at t0+30
    releases the source Batch's assignments. Neither side of either
    boundary is claimed for the wrong Batch; time outside the assignment is
    neither exposure nor gap."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0, carrier_count=2, sow_at=_m(t0, 10), place_at=_m(t0, 5))
    output_codes = [f"SPLIT-A-{s['suffix']}", f"SPLIT-B-{s['suffix']}"]
    split(
        db_session, tenant, user, farm, batch_id=s["batch"].id, output_codes=output_codes,
        source_assignment_ids=s["assignment_ids"], effective_time=_m(t0, 30),
    )
    source = _batch_timeline(db_session, tenant, farm, s["batch"].id, t0, 0, 60)
    # Two carriers, each on its own Grow Table under the mapped Zone.
    assert sorted(_shape(source["intervals"], t0)) == [(TOPO, 10, 30), (TOPO, 10, 30)]
    assert source["gaps"] == []
    for code in output_codes:
        output = _batch_timeline(db_session, tenant, farm, batch_id_by_code(db_session, tenant, code=code), t0, 0, 60)
        assert _shape(output["intervals"], t0) == [(TOPO, 30, 60)]
        assert output["gaps"] == []


def test_same_circuit_delivery_from_an_unlinked_reservoir_is_not_route_evidence(
    active_context_with_farm, db_session,
):
    """Exposure proof 5 (regression: 001A matched deliveries on Circuit only)."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, f"RES-B-{s['suffix']}")
    _record_delivery(
        db_session, tenant, user, farm, reservoir_id=reservoir_b.id, circuit_id=s["circuit"].id,
        start=_m(t0, 10), end=_m(t0, 20),
    )
    assert _shape(_circuit_intervals(db_session, tenant, farm, s, t0, 0, 60), t0) == [(TOPO, 0, 60)]
    for reservoir_id, expected in ((s["reservoir"].id, [(TOPO, 0, 60)]), (reservoir_b.id, [])):
        timeline = water_exposure_service.get_reservoir_water_exposure_timeline(
            db_session, tenant_id=tenant.id, farm_id=farm.id, reservoir_id=reservoir_id, window_start=_m(t0, 0),
            window_end=_m(t0, 60),
        )
        assert _shape(timeline["intervals"], t0) == expected


def _replumbed(db_session, tenant, user, farm, t0):
    """Circuit fed by Reservoir A until t0+30, then Reservoir B. Deliveries:
    A [10,20) (on route), A [35,38) (A no longer linked), B [40,50)."""
    s = _scenario(db_session, tenant, user, farm, t0)
    reservoir_b = _register_reservoir(db_session, tenant, user, farm, f"RES-B-{s['suffix']}")
    water_topology_service.close_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, link_id=s["rcl"].id, effective_to=_m(t0, 30),
    )
    water_topology_service.open_reservoir_circuit_link(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir_b.id,
        irrigation_circuit_id=s["circuit"].id, effective_from=_m(t0, 30), reason="re-plumbed",
    )
    for reservoir_id, start, end in ((s["reservoir"].id, 10, 20), (s["reservoir"].id, 35, 38), (reservoir_b.id, 40, 50)):
        _record_delivery(
            db_session, tenant, user, farm, reservoir_id=reservoir_id, circuit_id=s["circuit"].id,
            start=_m(t0, start), end=_m(t0, end),
        )
    s["reservoir_b"] = reservoir_b
    return s


def test_replumbing_a_circuit_produces_route_specific_intervals(active_context_with_farm, db_session):
    """Exposure proof 6."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _replumbed(db_session, tenant, user, farm, t0)
    intervals = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    by_reservoir = {
        rid: _shape([i for i in intervals if i["reservoir_id"] == rid], t0)
        for rid in (s["reservoir"].id, s["reservoir_b"].id)
    }
    assert by_reservoir[s["reservoir"].id] == [(TOPO, 0, 10), (REC, 10, 20), (TOPO, 20, 30)]
    assert by_reservoir[s["reservoir_b"].id] == [(TOPO, 30, 40), (REC, 40, 50), (TOPO, 50, 60)]
    legacy = water_exposure_service.get_water_exposure_history_for_batch(
        db_session, tenant_id=tenant.id, farm_id=farm.id, batch_id=s["batch"].id, window_start=_m(t0, 0),
        window_end=_m(t0, 60),
    )
    # Never one fact aggregating both reservoirs.
    assert all(len(r["reservoir_ids"]) == 1 for r in legacy)
    assert len(legacy) == 6


def test_forward_and_reverse_reads_agree_on_the_same_interval_facts(active_context_with_farm, db_session):
    """Exposure proof 11."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _replumbed(db_session, tenant, user, farm, t0)
    forward = _batch_timeline(db_session, tenant, farm, s["batch"].id, t0, 0, 60)["intervals"]
    circuit = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    reservoirs = [
        i
        for rid in (s["reservoir"].id, s["reservoir_b"].id)
        for i in water_exposure_service.get_reservoir_water_exposure_timeline(
            db_session, tenant_id=tenant.id, farm_id=farm.id, reservoir_id=rid, window_start=_m(t0, 0),
            window_end=_m(t0, 60),
        )["intervals"]
    ]
    facts = {_fact(i) for i in forward}
    assert len(facts) == 6
    assert facts == {_fact(i) for i in circuit if i["batch_id"] == s["batch"].id}
    assert facts == {_fact(i) for i in reservoirs if i["batch_id"] == s["batch"].id}


def test_closing_an_open_delivery_ends_recorded_exposure_at_the_closure(active_context_with_farm, db_session):
    """Exposure proofs 7 + 8. Before closure the open delivery is clipped to
    `window_end` and flagged, with nothing persisted; after the End Delivery
    command, recorded exposure stops at the closure time."""
    tenant, user, _headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    delivery = _record_delivery(
        db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
        start=_m(t0, 10), end=None,
    )
    raw_before = _raw_delivery_row(db_session, delivery.id)
    open_intervals = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    assert _shape(open_intervals, t0) == [(TOPO, 0, 10), (REC, 10, 60)]
    recorded = open_intervals[1]
    assert recorded["end_clipped_to_window"] is True
    assert "WATER_DELIVERY_EVENT" in recorded["open_ended_sources"]
    assert open_intervals[0]["open_ended_sources"] == []  # ended at 10, not clipped
    # Reading never persisted an end.
    assert _raw_delivery_row(db_session, delivery.id) == raw_before
    assert _end_row_count(db_session, delivery.id) == 0

    _end(db_session, tenant, user, farm, delivery.id, _m(t0, 25))
    closed_intervals = _circuit_intervals(db_session, tenant, farm, s, t0, 0, 60)
    assert _shape(closed_intervals, t0) == [(TOPO, 0, 10), (REC, 10, 25), (TOPO, 25, 60)]
    assert closed_intervals[1]["end_clipped_to_window"] is False
    assert closed_intervals[1]["open_ended_sources"] == []
    assert "WATER_DELIVERY_EVENT" not in closed_intervals[2]["open_ended_sources"]


def test_exposure_is_isolated_across_farms_and_tenants(active_context_with_farm, db_session, client):
    """Exposure proof 10."""
    tenant, user, headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    farm_b = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"fb-{uuid.uuid4().hex[:6]}", name="Farm B",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    s_b = _scenario(db_session, tenant, user, farm_b, t0)
    for scenario, scenario_farm in ((s, farm), (s_b, farm_b)):
        own = _circuit_intervals(db_session, tenant, scenario_farm, scenario, t0, 0, 60)
        assert {i["batch_id"] for i in own} == {scenario["batch"].id}
    # Farm A's circuit queried under Farm B's scope, and the reverse.
    assert _circuit_intervals(db_session, tenant, farm_b, s, t0, 0, 60) == []
    assert _circuit_intervals(db_session, tenant, farm, s_b, t0, 0, 60) == []
    other_tenant, other_headers = _other_tenant_headers(db_session)
    assert water_exposure_service.get_batch_water_exposure_timeline(
        db_session, tenant_id=other_tenant.id, farm_id=farm.id, batch_id=s["batch"].id, window_start=_m(t0, 0),
        window_end=_m(t0, 60),
    )["intervals"] == []
    params = {"farm_id": str(farm.id), "window_start": _m(t0, 0).isoformat(), "window_end": _m(t0, 60).isoformat()}
    response = client.get(f"/irrigation-circuits/{s['circuit'].id}/water-exposure-timeline", headers=other_headers, params=params)
    assert response.status_code in (403, 404) or response.json()["intervals"] == []


def test_exposure_http_contract_window_validation_and_no_forbidden_wording(
    active_context_with_farm, db_session, client,
):
    """Exposure proof 12 plus the API-boundary window rules: every exposure
    endpoint returns the explicit half-open convention, rejects
    `window_start >= window_end` and naive timestamps, and never emits
    disease/contamination wording."""
    tenant, user, headers, farm = active_context_with_farm
    t0 = _t0()
    s = _scenario(db_session, tenant, user, farm, t0)
    _record_delivery(
        db_session, tenant, user, farm, reservoir_id=s["reservoir"].id, circuit_id=s["circuit"].id,
        start=_m(t0, 20), end=_m(t0, 30),
    )
    paths = [
        f"/crop-batches/{s['batch'].id}/water-exposure-timeline",
        f"/irrigation-circuits/{s['circuit'].id}/water-exposure-timeline",
        f"/reservoirs/{s['reservoir'].id}/water-exposure-timeline",
        f"/crop-batches/{s['batch'].id}/water-exposure",
        f"/irrigation-circuits/{s['circuit'].id}/exposed-placements",
        f"/reservoirs/{s['reservoir'].id}/exposed-placements",
    ]
    params = {"farm_id": str(farm.id), "window_start": _m(t0, 0).isoformat(), "window_end": _m(t0, 60).isoformat()}
    for path in paths:
        response = client.get(path, headers=headers, params=params)
        assert response.status_code == 200, (path, response.text)
        dumped = json.dumps(response.json()).lower()
        for word in FORBIDDEN_WORDS:
            assert word not in dumped, (path, word)
        payload = response.json()
        if isinstance(payload, dict):
            assert payload["interval_convention"] == "HALF_OPEN_START_INCLUSIVE_END_EXCLUSIVE"
            assert [i["exposure_kind"] for i in payload["intervals"]] == [TOPO, REC, TOPO]
        else:
            assert len(payload) == 3

    batch_timeline = client.get(paths[0], headers=headers, params=params).json()
    assert set(batch_timeline) == {
        "batch_id", "farm_id", "window_start", "window_end", "interval_convention", "intervals", "gaps",
    }
    assert batch_timeline["gaps"] == []

    for bad in (
        {**params, "window_end": params["window_start"]},
        {**params, "window_start": _m(t0, 60).isoformat(), "window_end": _m(t0, 0).isoformat()},
        {**params, "window_start": _m(t0, 0).replace(tzinfo=None).isoformat()},
    ):
        for path in paths:
            assert client.get(path, headers=headers, params=bad).status_code == 422, (path, bad)
