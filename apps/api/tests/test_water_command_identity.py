"""UX-OPS-001D (N03): complete request identity for the four operational
Water write commands -- Measurement, Nutrient Mix, Reservoir Event, Water
Delivery Event.

Proves, per command: the same complete payload replays with no second
domain/child/audit row; every formerly omitted material field (and farm
path scope) conflicts and creates nothing; the null "server now" sentinel
still replays; equivalent instants in different offsets are one fact; and
rows recorded under the PILOT-WATER-001A legacy fingerprint replay only
when every persisted fact matches."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest
from sqlalchemy import func, select

from app.models.audit_event import AuditEvent
from app.models.nutrient_mix import NutrientMix
from app.models.nutrient_mix_input import NutrientMixInput
from app.models.reservoir_event import ReservoirEvent
from app.models.unit_of_measure import UnitOfMeasure
from app.models.water_delivery_event import WaterDeliveryEvent
from app.models.water_measurement import WaterMeasurement
from app.services import (
    farm_service,
    nutrient_mix_service,
    reservoir_operations_service,
    sampling_point_service,
    water_command_identity,
    water_instrument_service,
    water_topology_service,
)
from app.services.errors import (
    NutrientMixValidationError,
    ReservoirEventValidationError,
    WaterDeliveryEventValidationError,
    WaterMeasurementValidationError,
)

T0 = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)


@dataclass
class Ctx:
    db: object
    tenant: object
    user: object
    farm: object
    other_farm: object
    reservoir: object
    circuit: object
    sampling_point: object
    mix: object
    litre: object
    millilitre: object


@pytest.fixture
def ctx(active_context_with_farm, db_session) -> Ctx:
    tenant, user, _headers, farm = active_context_with_farm
    suffix = uuid.uuid4().hex[:8]
    other_farm = farm_service.create_farm(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, code=f"other-{suffix}", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    reservoir = water_topology_service.register_reservoir(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"RES-{suffix}",
        name="Reservoir", reservoir_type="nutrient_reservoir", nominal_capacity=None, nominal_capacity_uom_id=None,
        linked_asset_id=None, location_id=None, notes=None,
    )
    circuit = water_topology_service.register_irrigation_circuit(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"IC-{suffix}",
        name="Circuit", system_type="dwc", notes=None,
    )
    sampling_point = sampling_point_service.register_sampling_point(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, code=f"SP-{suffix}",
        name="Tank sample", point_type="reservoir", anchor_id=reservoir.id, notes=None,
    )
    litre = db_session.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == "L")).scalar_one()
    millilitre = db_session.execute(select(UnitOfMeasure).where(UnitOfMeasure.code == "mL")).scalar_one()
    mix = nutrient_mix_service.record_mix(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, reservoir_id=reservoir.id,
        nutrient_recipe_version_id=None, effective_at=T0, target_volume=None, target_volume_uom_id=None,
        actual_volume=None, actual_volume_uom_id=None, notes=None, client_command_id=uuid.uuid4(),
        inputs=[{
            "inventory_item_id": None, "component_label": "Seed mix", "actual_quantity": "1",
            "actual_quantity_uom_id": litre.id, "sequence_number": 1, "note": None,
        }],
    )
    return Ctx(db_session, tenant, user, farm, other_farm, reservoir, circuit, sampling_point, mix, litre, millilitre)


# --- Command specs --------------------------------------------------------------------


@dataclass
class Spec:
    name: str
    base: Callable[[Ctx], dict]
    call: Callable[..., object]
    model: type
    audit_action: str
    error: type
    time_field: str


def _measurement_base(c: Ctx) -> dict:
    return {
        "farm_id": c.farm.id, "sampling_point_id": c.sampling_point.id, "metric": "EC", "value": "1.8",
        "unit": "mS/cm", "effective_at": T0, "water_instrument_id": None, "notes": None,
    }


def _mix_base(c: Ctx) -> dict:
    return {
        "farm_id": c.farm.id, "reservoir_id": c.reservoir.id, "nutrient_recipe_version_id": None,
        "effective_at": T0, "target_volume": "500", "target_volume_uom_id": c.litre.id,
        "actual_volume": "480", "actual_volume_uom_id": c.litre.id, "notes": None,
        "inputs": [
            {"inventory_item_id": None, "component_label": "Stock A", "actual_quantity": "2.5",
             "actual_quantity_uom_id": c.litre.id, "sequence_number": 1, "note": None},
            {"inventory_item_id": None, "component_label": "Stock B", "actual_quantity": "2.5",
             "actual_quantity_uom_id": c.litre.id, "sequence_number": 2, "note": "after A"},
        ],
    }


def _reservoir_event_base(c: Ctx) -> dict:
    return {
        "farm_id": c.farm.id, "reservoir_id": c.reservoir.id, "event_type": "WATER_TOP_UP", "effective_at": T0,
        "quantity": "50", "quantity_uom_id": c.litre.id, "inventory_item_id": None, "notes": None,
    }


def _delivery_base(c: Ctx) -> dict:
    return {
        "farm_id": c.farm.id, "reservoir_id": c.reservoir.id, "irrigation_circuit_id": c.circuit.id,
        "effective_start": T0, "effective_end": None, "delivered_volume": "120",
        "delivered_volume_uom_id": c.litre.id, "nutrient_mix_id": c.mix.id, "notes": None,
    }


def _call_measurement(c: Ctx, **kw):
    return water_instrument_service.record_measurement(c.db, tenant_id=c.tenant.id, actor_user_id=c.user.id, **kw)


def _call_mix(c: Ctx, **kw):
    return nutrient_mix_service.record_mix(c.db, tenant_id=c.tenant.id, actor_user_id=c.user.id, **kw)


def _call_reservoir_event(c: Ctx, **kw):
    return reservoir_operations_service.record_reservoir_event(
        c.db, tenant_id=c.tenant.id, actor_user_id=c.user.id, **kw
    )


def _call_delivery(c: Ctx, **kw):
    return reservoir_operations_service.record_delivery_event(
        c.db, tenant_id=c.tenant.id, actor_user_id=c.user.id, **kw
    )


SPECS = {
    "measurement": Spec("measurement", _measurement_base, _call_measurement, WaterMeasurement,
                        "water_measurement.recorded", WaterMeasurementValidationError, "effective_at"),
    "mix": Spec("mix", _mix_base, _call_mix, NutrientMix, "nutrient_mix.recorded",
                NutrientMixValidationError, "effective_at"),
    "reservoir_event": Spec("reservoir_event", _reservoir_event_base, _call_reservoir_event, ReservoirEvent,
                            "reservoir_event.recorded", ReservoirEventValidationError, "effective_at"),
    "delivery": Spec("delivery", _delivery_base, _call_delivery, WaterDeliveryEvent,
                     "water_delivery_event.recorded", WaterDeliveryEventValidationError, "effective_start"),
}


def _counts(c: Ctx, spec: Spec) -> tuple[int, int, int]:
    rows = c.db.execute(select(func.count()).select_from(spec.model).where(spec.model.tenant_id == c.tenant.id))
    audits = c.db.execute(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == c.tenant.id, AuditEvent.action == spec.audit_action
        )
    )
    inputs = c.db.execute(
        select(func.count()).select_from(NutrientMixInput).where(NutrientMixInput.tenant_id == c.tenant.id)
    )
    return rows.scalar_one(), audits.scalar_one(), inputs.scalar_one()


# --- 1. Same complete payload replays -------------------------------------------------


@pytest.mark.parametrize("kind", list(SPECS))
def test_same_complete_payload_replays_one_row_one_audit(ctx, kind):
    spec = SPECS[kind]
    command_id = uuid.uuid4()
    payload = spec.base(ctx) | {"notes": "first pass"}
    first = spec.call(ctx, client_command_id=command_id, **payload)
    after_first = _counts(ctx, spec)
    replay = spec.call(ctx, client_command_id=command_id, **spec.base(ctx) | {"notes": "first pass"})
    assert replay.id == first.id
    assert _counts(ctx, spec) == after_first  # no second domain row, child row, or audit event


# --- 2/3/4. Formerly omitted fields, ordered Mix inputs, and farm scope conflict ------


def _set_input(index: int, **changes):
    def mutate(c: Ctx, p: dict) -> dict:
        inputs = [dict(i) for i in p["inputs"]]
        inputs[index] = inputs[index] | changes
        return p | {"inputs": inputs}
    return mutate


def _uom(field: str):
    return lambda c, p: p | {field: c.millilitre.id}


CONFLICTS = [
    ("measurement", "notes null vs empty", lambda c, p: p | {"notes": ""}),
    ("measurement", "notes text", lambda c, p: p | {"notes": "different"}),
    ("measurement", "farm path scope", lambda c, p: p | {"farm_id": c.other_farm.id}),
    ("mix", "notes null vs empty", lambda c, p: p | {"notes": ""}),
    ("mix", "farm path scope", lambda c, p: p | {"farm_id": c.other_farm.id}),
    ("mix", "target volume UOM", _uom("target_volume_uom_id")),
    ("mix", "actual volume UOM", _uom("actual_volume_uom_id")),
    ("mix", "input UOM", lambda c, p: _set_input(0, actual_quantity_uom_id=c.millilitre.id)(c, p)),
    ("mix", "input sequence number", _set_input(0, sequence_number=3)),
    ("mix", "input note null vs empty", _set_input(0, note="")),
    ("mix", "input note text", _set_input(1, note="before A")),
    ("mix", "input order", lambda c, p: p | {"inputs": list(reversed(p["inputs"]))}),
    ("reservoir_event", "notes null vs empty", lambda c, p: p | {"notes": ""}),
    ("reservoir_event", "farm path scope", lambda c, p: p | {"farm_id": c.other_farm.id}),
    ("delivery", "notes null vs empty", lambda c, p: p | {"notes": ""}),
    ("delivery", "delivered volume UOM", _uom("delivered_volume_uom_id")),
    ("delivery", "farm path scope", lambda c, p: p | {"farm_id": c.other_farm.id}),
]


@pytest.mark.parametrize(("kind", "change", "mutate"), CONFLICTS, ids=[f"{k}:{n}" for k, n, _ in CONFLICTS])
def test_changed_material_field_conflicts_and_creates_nothing(ctx, kind, change, mutate):
    spec = SPECS[kind]
    command_id = uuid.uuid4()
    spec.call(ctx, client_command_id=command_id, **spec.base(ctx))
    before = _counts(ctx, spec)
    with pytest.raises(spec.error, match="reused with a different payload"):
        spec.call(ctx, client_command_id=command_id, **mutate(ctx, spec.base(ctx)))
    assert _counts(ctx, spec) == before


# --- 5. Null "server now" still replays; equivalent instants are one fact -------------


@pytest.mark.parametrize("kind", list(SPECS))
def test_null_server_now_retry_replays_the_original_effective_time(ctx, kind):
    spec = SPECS[kind]
    command_id = uuid.uuid4()
    first = spec.call(ctx, client_command_id=command_id, **spec.base(ctx) | {spec.time_field: None})
    before = _counts(ctx, spec)
    retry = spec.call(ctx, client_command_id=command_id, **spec.base(ctx) | {spec.time_field: None})
    assert retry.id == first.id
    assert getattr(retry, spec.time_field) == getattr(first, spec.time_field)
    assert _counts(ctx, spec) == before
    # The resolved instant is not the request: sending it explicitly is a
    # different command payload.
    with pytest.raises(spec.error):
        spec.call(ctx, client_command_id=command_id, **spec.base(ctx) | {spec.time_field: getattr(first, spec.time_field)})


@pytest.mark.parametrize("kind", list(SPECS))
def test_same_instant_in_another_offset_replays(ctx, kind):
    spec = SPECS[kind]
    command_id = uuid.uuid4()
    first = spec.call(ctx, client_command_id=command_id, **spec.base(ctx))
    dubai = T0.astimezone(timezone(timedelta(hours=4)))
    replay = spec.call(ctx, client_command_id=command_id, **spec.base(ctx) | {spec.time_field: dubai})
    assert replay.id == first.id


# --- 6. Legacy-fingerprint rows (recorded before N03) ---------------------------------


def _insert_legacy(c: Ctx, kind: str, command_id: uuid.UUID, payload: dict, *, requested_time):
    """Inserts a row exactly as the PILOT-WATER-001A code stored it: the
    legacy fingerprint computed from the REQUEST (a null "now" encoded as
    `""`), with the server-resolved effective time persisted."""
    legacy = water_command_identity.legacy_fingerprint
    t = c.tenant.id
    if kind == "measurement":
        fp = legacy(t, payload["sampling_point_id"], payload["metric"], payload["value"], payload["unit"],
                    requested_time, payload["water_instrument_id"])
        row = WaterMeasurement(
            tenant_id=t, farm_id=payload["farm_id"], sampling_point_id=payload["sampling_point_id"],
            metric=payload["metric"], value=payload["value"], unit=payload["unit"], effective_at=T0,
            recorded_by_user_id=c.user.id, water_instrument_id=None, notes=payload["notes"],
            client_command_id=command_id, request_fingerprint=fp,
        )
        c.db.add(row)
    elif kind == "mix":
        fp = legacy(t, payload["reservoir_id"], payload["nutrient_recipe_version_id"], requested_time,
                    payload["target_volume"], payload["actual_volume"],
                    tuple((i["inventory_item_id"], i["component_label"], i["actual_quantity"]) for i in payload["inputs"]))
        row = NutrientMix(
            tenant_id=t, farm_id=payload["farm_id"], reservoir_id=payload["reservoir_id"],
            nutrient_recipe_version_id=None, prepared_by_user_id=c.user.id, effective_at=T0,
            target_volume=payload["target_volume"], target_volume_uom_id=payload["target_volume_uom_id"],
            actual_volume=payload["actual_volume"], actual_volume_uom_id=payload["actual_volume_uom_id"],
            notes=payload["notes"], client_command_id=command_id, request_fingerprint=fp,
        )
        c.db.add(row)
        c.db.flush()
        for i in payload["inputs"]:
            c.db.add(NutrientMixInput(tenant_id=t, farm_id=payload["farm_id"], nutrient_mix_id=row.id, **i))
    elif kind == "reservoir_event":
        fp = legacy(t, payload["reservoir_id"], payload["event_type"], requested_time, payload["quantity"],
                    payload["quantity_uom_id"], payload["inventory_item_id"])
        row = ReservoirEvent(
            tenant_id=t, farm_id=payload["farm_id"], reservoir_id=payload["reservoir_id"],
            event_type=payload["event_type"], effective_at=T0, operator_user_id=c.user.id,
            quantity=payload["quantity"], quantity_uom_id=payload["quantity_uom_id"], inventory_item_id=None,
            notes=payload["notes"], client_command_id=command_id, request_fingerprint=fp,
        )
        c.db.add(row)
    else:
        fp = legacy(t, payload["reservoir_id"], payload["irrigation_circuit_id"], requested_time,
                    payload["effective_end"], payload["delivered_volume"], payload["nutrient_mix_id"])
        row = WaterDeliveryEvent(
            tenant_id=t, farm_id=payload["farm_id"], reservoir_id=payload["reservoir_id"],
            irrigation_circuit_id=payload["irrigation_circuit_id"], effective_start=T0, effective_end=None,
            delivered_volume=payload["delivered_volume"], delivered_volume_uom_id=payload["delivered_volume_uom_id"],
            recorded_by_user_id=c.user.id, nutrient_mix_id=payload["nutrient_mix_id"], notes=payload["notes"],
            client_command_id=command_id, request_fingerprint=fp,
        )
        c.db.add(row)
    c.db.commit()
    return row


LEGACY_OMITTED_FIELD_CHANGES = {
    "measurement": lambda c, p: p | {"notes": "changed"},
    "mix": _set_input(1, note="changed"),
    "reservoir_event": lambda c, p: p | {"notes": "changed"},
    "delivery": _uom("delivered_volume_uom_id"),
}


@pytest.mark.parametrize("kind", list(SPECS))
@pytest.mark.parametrize("requested_time", ["explicit", "server_now"])
def test_legacy_fingerprint_row_replays_only_when_persisted_facts_match(ctx, kind, requested_time):
    spec = SPECS[kind]
    command_id = uuid.uuid4()
    payload = spec.base(ctx) | {"notes": "legacy note"}
    time_value = T0 if requested_time == "explicit" else None
    legacy_row = _insert_legacy(ctx, kind, command_id, payload, requested_time=time_value)
    before = _counts(ctx, spec)

    replay = spec.call(ctx, client_command_id=command_id, **payload | {spec.time_field: time_value})
    assert replay.id == legacy_row.id
    assert _counts(ctx, spec) == before

    # A formerly omitted field that differs is a conflict, never a replay.
    changed = LEGACY_OMITTED_FIELD_CHANGES[kind](ctx, payload | {spec.time_field: time_value})
    with pytest.raises(spec.error, match="reused with a different payload"):
        spec.call(ctx, client_command_id=command_id, **changed)
    # So is farm path scope.
    with pytest.raises(spec.error, match="reused with a different payload"):
        spec.call(ctx, client_command_id=command_id, **payload | {spec.time_field: time_value, "farm_id": ctx.other_farm.id})
    assert _counts(ctx, spec) == before


# --- HTTP: a command-ID payload mismatch stays a definitive 4xx ----------------------


def test_command_id_payload_mismatch_is_a_definitive_client_error_over_http(
    ctx, client, active_context_with_farm, monkeypatch
):
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", True)
    _tenant, _user, headers, farm = active_context_with_farm
    command_id = str(uuid.uuid4())
    requests = [
        (f"/farms/{farm.id}/sampling-points/{ctx.sampling_point.id}/measurements",
         {"metric": "PH", "value": "6.1", "unit": "pH", "notes": None}, 422),
        (f"/farms/{farm.id}/reservoirs/{ctx.reservoir.id}/nutrient-mixes",
         {"notes": None, "inputs": [{"component_label": "A", "actual_quantity": "1",
                                     "actual_quantity_uom_id": str(ctx.litre.id)}]}, 409),
        (f"/farms/{farm.id}/reservoirs/{ctx.reservoir.id}/events", {"event_type": "FLUSH", "notes": None}, 409),
        (f"/farms/{farm.id}/water-delivery-events",
         {"reservoir_id": str(ctx.reservoir.id), "irrigation_circuit_id": str(ctx.circuit.id), "notes": None}, 409),
    ]
    for index, (path, body, conflict_status) in enumerate(requests):
        command = {**body, "client_command_id": f"{command_id[:-2]}{index:02d}"}
        first = client.post(path, headers=headers, json=command)
        assert first.status_code == 201, first.text
        again = client.post(path, headers=headers, json=command)
        assert again.status_code == 201 and again.json()["id"] == first.json()["id"]
        changed = client.post(path, headers=headers, json=command | {"notes": ""})
        assert changed.status_code == conflict_status, (path, changed.text)
