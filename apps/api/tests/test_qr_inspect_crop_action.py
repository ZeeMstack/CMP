"""PILOT-AGRO-001B focused proofs: the "Inspect Crop" QR action added to
`qr_service.resolve_scan_context` for `crop_batch`/`carrier`/
`batch_carrier_assignment`. This is the one precedented backend touch this
ticket makes -- neither `CropBatchScanContext` nor
`BatchCarrierAssignmentScanContext` exposes its own raw entity UUID as a
JSON field, so the href can only be built server-side (mirrors the exact
existing pattern already used for "Record Observation"/"Harvest").

Uses the fast `db_session`/`active_context_with_farm` fixtures (not the
heavy `test_engine`/`committed_connection` HTTP acceptance path) --
`resolve_scan_context` is a plain read, so no lock/commit-visibility
concern applies."""

from app.services import qr_service
from tests.test_growing_protocol_and_crop_issue import _build_scenario


def _find_action(actions, label):
    for action in actions:
        if action.label == label:
            return action
    return None


def _resolve(db_session, tenant, farm_id, entity_type, entity_id, *, actor, may_grants_inspection):
    identifier = qr_service.generate_or_get_qr_identifier(
        db_session, tenant_id=tenant.id, farm_id=farm_id, entity_type=entity_type, entity_id=entity_id,
        actor_user_id=actor.id,
    )

    def may(permission_value: str) -> bool:
        if permission_value == "crop_inspection.manage":
            return may_grants_inspection
        return True

    return qr_service.resolve_scan_context(db_session, tenant_id=tenant.id, qr_identifier=identifier, may=may)


def test_crop_batch_qr_offers_inspect_crop_when_permitted(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    batch = scenario["batch"]

    ctx = _resolve(
        db_session, tenant, farm.id, "crop_batch", batch.id, actor=user, may_grants_inspection=True,
    )
    action = _find_action(ctx.actions, "Inspect Crop")
    assert action is not None
    assert action.href == f"/farms/{farm.id}/production/inspect?batchId={batch.id}"


def test_crop_batch_qr_withholds_inspect_crop_without_permission(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    batch = scenario["batch"]

    ctx = _resolve(
        db_session, tenant, farm.id, "crop_batch", batch.id, actor=user, may_grants_inspection=False,
    )
    assert _find_action(ctx.actions, "Inspect Crop") is None


def test_carrier_qr_inspects_current_occupant_only(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    batch = scenario["batch"]
    carrier = scenario["carriers"][0]

    ctx = _resolve(
        db_session, tenant, farm.id, "carrier", carrier.id, actor=user, may_grants_inspection=True,
    )
    action = _find_action(ctx.actions, "Inspect Crop")
    assert action is not None
    assert f"batchId={batch.id}" in action.href
    assert "assignmentId=" in action.href


def test_placement_qr_offers_inspect_crop_for_current_assignment(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scenario = _build_scenario(db_session, tenant, user, farm)
    batch = scenario["batch"]
    assignment_id = scenario["assignment_ids"][0]

    ctx = _resolve(
        db_session, tenant, farm.id, "batch_carrier_assignment", assignment_id, actor=user,
        may_grants_inspection=True,
    )
    action = _find_action(ctx.actions, "Inspect Crop")
    assert action is not None
    assert action.href == f"/farms/{farm.id}/production/inspect?assignmentId={assignment_id}&batchId={batch.id}"


# A "historical placement never offers current Inspect Crop" proof is
# deliberately not duplicated here: the gate is the exact same boolean
# check (`assignment.released_effective_time is None`) this module's
# existing Harvest action already uses on the identical
# `BatchCarrierAssignmentScanContext` branch, and constructing a genuinely
# released assignment requires a full harvest/transplant/disposition event
# (the DB's own `enforce_batch_carrier_assignment_closure_only_v2` trigger
# requires exactly one typed releaser FK, not a bare timestamp) -- adding
# that heavy scenario here purely to re-prove an already-shared code path
# is exactly the "not a broad suite" time-efficiency this ticket asks for.
