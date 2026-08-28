"""PILOT-READY-001: dispatch_temperature_c is one factual Celsius reading
per DispatchEvent (whole dispatch/vehicle), required on every new command,
returned on read, never per line/lot/product, and participates in the
idempotency fingerprint like every other command field. All via the HTTP
API, reusing test_dispatch_acceptance's own farm/crop/harvest/pack setup
helper rather than duplicating it."""
import uuid
from decimal import Decimal

import pytest

from tests.test_dispatch_acceptance import _build_finished_goods_lot, _now_iso


@pytest.mark.integration
def test_dispatch_requires_temperature(client, active_context) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Temp Farm", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]
    fg_lot_id, _batch_id = _build_finished_goods_lot(client, headers, farm_id, suffix, package_count=10, packed_weight="8.000")

    # A: missing dispatch_temperature_c is rejected -- no default, no silent success.
    missing_temp_resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-notemp-{suffix}",
            "external_reference": None, "note": None,
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
        },
    )
    assert missing_temp_resp.status_code == 422, missing_temp_resp.text

    # B: recorded value is returned on read, and C: one reading covers a
    # multi-FG-lot dispatch, and D: no line ever receives its own reading.
    fg_lot_id_2, _batch_id_2 = _build_finished_goods_lot(
        client, headers, farm_id, suffix + "B", package_count=10, packed_weight="8.000"
    )
    command_id = str(uuid.uuid4())
    payload = {
        "client_command_id": command_id, "effective_time": _now_iso(), "code": f"disp-temp-{suffix}",
        "external_reference": None, "note": None, "dispatch_temperature_c": "-18.5",
        "lines": [
            {"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1},
            {"finished_goods_lot_id": fg_lot_id_2, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1},
        ],
    }
    resp = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=payload)
    assert resp.status_code == 201, resp.text
    event = resp.json()
    assert event["dispatch_temperature_c"] == "-18.5"
    assert len(event["lines"]) == 2
    for line in event["lines"]:
        assert "dispatch_temperature_c" not in line

    detail = client.get(f"/farms/{farm_id}/dispatches/{event['id']}", headers=headers).json()
    assert detail["dispatch_temperature_c"] == "-18.5"

    # E: idempotent replay (identical payload, same client_command_id)
    # returns the same event and preserves the original temperature.
    replay_resp = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=payload)
    assert replay_resp.status_code == 201
    assert replay_resp.json()["id"] == event["id"]
    assert replay_resp.json()["dispatch_temperature_c"] == "-18.5"

    # F: same client_command_id, only the temperature changed -> treated as
    # a changed payload, same conflict rule as any other field.
    changed_payload = dict(payload)
    changed_payload["dispatch_temperature_c"] = "-15.0"
    conflict_resp = client.post(f"/farms/{farm_id}/dispatches", headers=headers, json=changed_payload)
    assert conflict_resp.status_code == 409, conflict_resp.text


@pytest.mark.integration
def test_dispatch_temperature_out_of_sane_range_rejected(client, active_context) -> None:
    _tenant, _user, headers = active_context
    suffix = uuid.uuid4().hex[:8].upper()

    farm = client.post(
        "/farms", headers=headers,
        json={"code": f"farm-{suffix}", "name": "Temp Farm 2", "country_code": "AE", "timezone": "Asia/Dubai"},
    ).json()
    farm_id = farm["id"]
    fg_lot_id, _batch_id = _build_finished_goods_lot(client, headers, farm_id, suffix, package_count=10, packed_weight="8.000")

    resp = client.post(
        f"/farms/{farm_id}/dispatches", headers=headers,
        json={
            "client_command_id": str(uuid.uuid4()), "effective_time": _now_iso(), "code": f"disp-badtemp-{suffix}",
            "external_reference": None, "note": None, "dispatch_temperature_c": "999",
            "lines": [{"finished_goods_lot_id": fg_lot_id, "dispatched_weight_kg": "1.000", "dispatched_package_count": 1}],
        },
    )
    assert resp.status_code == 422, resp.text
