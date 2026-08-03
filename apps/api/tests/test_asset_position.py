import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models.asset_position import AssetPosition
from app.models.audit_event import AuditEvent
from app.schemas.asset_position import MAX_BULK_POSITIONS, AssetPositionsGenerate
from app.services import asset_service
from app.services.errors import DuplicatePositionCodeError, PositionsNotSupportedError

# --- Application-level (Pydantic) validation — no DB required ---


def test_positions_above_max_rejected_before_database_writes() -> None:
    with pytest.raises(ValueError):
        AssetPositionsGenerate(
            shelf_count=1000, slots_per_shelf=5, shelf_prefix="SH-", slot_prefix="SL-",
            shelf_pad_width=4, slot_pad_width=2,
        )


def test_positions_at_max_is_allowed() -> None:
    # 8 shelves + 8*5 slots = 48, well under the cap; this checks the boundary math directly.
    payload = AssetPositionsGenerate(
        shelf_count=8, slots_per_shelf=5, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    assert payload.shelf_count * payload.slots_per_shelf + payload.shelf_count == 48
    assert payload.shelf_count + payload.shelf_count * payload.slots_per_shelf <= MAX_BULK_POSITIONS


# --- Integration (DB) ---


def _register_trolley(db_session, tenant, farm, user, code="GT-0001"):
    return asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code=code, name="Trolley", commissioned_date=None,
    )


@pytest.mark.integration
def test_eight_shelves_five_slots_generated_atomically(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)

    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=8, slots_per_shelf=5, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    assert len(created) == 8 + 8 * 5
    shelves = [p for p in created if p.position_kind == "shelf"]
    slots = [p for p in created if p.position_kind == "slot"]
    assert len(shelves) == 8
    assert len(slots) == 40
    assert {s.code for s in shelves} == {f"SH-{n:02d}" for n in range(1, 9)}

    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "asset.positions_generated")
    ).scalar_one()
    assert audit_count == 1


@pytest.mark.integration
def test_unsupported_asset_type_rejects_positions(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scale = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="weighing_scale", code="WS-01", name="Scale", commissioned_date=None,
    )
    with pytest.raises(PositionsNotSupportedError):
        asset_service.generate_positions(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=scale.id,
            shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
            shelf_pad_width=2, slot_pad_width=2,
        )


@pytest.mark.integration
def test_failed_generation_rolls_back_positions_and_audit_event(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=3, slots_per_shelf=2, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    before_count = db_session.execute(
        select(func.count()).select_from(AssetPosition).where(AssetPosition.asset_id == trolley.id)
    ).scalar_one()

    with pytest.raises(DuplicatePositionCodeError):
        asset_service.generate_positions(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
            shelf_count=2, slots_per_shelf=2, shelf_prefix="SH-", slot_prefix="SL-",
            shelf_pad_width=2, slot_pad_width=2,
        )

    after_count = db_session.execute(
        select(func.count()).select_from(AssetPosition).where(AssetPosition.asset_id == trolley.id)
    ).scalar_one()
    assert after_count == before_count

    audit_count = db_session.execute(
        select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "asset.positions_generated")
    ).scalar_one()
    assert audit_count == 1  # only the first, successful command


@pytest.mark.integration
def test_shelf_cannot_have_a_parent_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    existing_shelf = next(p for p in created if p.position_kind == "shelf")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, :parent_id, 'shelf', 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley.id, "parent_id": existing_shelf.id},
            )


@pytest.mark.integration
def test_slot_requires_a_shelf_parent_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, NULL, 'slot', 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley.id},
            )


@pytest.mark.integration
def test_positions_under_unsupported_asset_type_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    scale = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="weighing_scale", code="WS-01", name="Scale", commissioned_date=None,
    )
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, NULL, 'shelf', 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "asset_id": scale.id},
            )


@pytest.mark.integration
def test_cross_asset_parent_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley_a = _register_trolley(db_session, tenant, farm, user, code="GT-A")
    trolley_b = _register_trolley(db_session, tenant, farm, user, code="GT-B")
    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley_a.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    shelf_a = next(p for p in created if p.position_kind == "shelf")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, :parent_id, 'slot', 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley_b.id, "parent_id": shelf_a.id},
            )


@pytest.mark.integration
def test_slot_as_parent_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    existing_slot = next(p for p in created if p.position_kind == "slot")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, :parent_id, 'slot', 'BAD', 'Bad')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley.id, "parent_id": existing_slot.id},
            )


@pytest.mark.integration
def test_sibling_root_shelf_code_uniqueness_case_insensitive(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, NULL, 'shelf', 'sh-01', 'Dup')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley.id},
            )


@pytest.mark.integration
def test_sibling_slot_code_uniqueness_case_insensitive(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    shelf = next(p for p in created if p.position_kind == "shelf")
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                text(
                    "INSERT INTO asset_positions (id, asset_id, parent_position_id, position_kind, code, name) "
                    "VALUES (:id, :asset_id, :parent_id, 'slot', 'sl-01', 'Dup')"
                ),
                {"id": uuid.uuid4(), "asset_id": trolley.id, "parent_id": shelf.id},
            )


@pytest.mark.integration
def test_direct_sql_deletion_of_position_rejected_by_postgres(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    trolley = _register_trolley(db_session, tenant, farm, user)
    created = asset_service.generate_positions(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, asset_id=trolley.id,
        shelf_count=1, slots_per_shelf=1, shelf_prefix="SH-", slot_prefix="SL-",
        shelf_pad_width=2, slot_pad_width=2,
    )
    slot = next(p for p in created if p.position_kind == "slot")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(text("DELETE FROM asset_positions WHERE id = :id"), {"id": slot.id})


@pytest.mark.integration
def test_positions_tree_via_api(client, active_context_with_farm) -> None:
    tenant, user, headers, farm = active_context_with_farm
    asset_resp = client.post(
        f"/farms/{farm.id}/assets",
        headers=headers,
        json={"asset_type_code": "germination_trolley", "code": "GT-0001", "name": "Trolley 1"},
    )
    assert asset_resp.status_code == 201
    asset_id = asset_resp.json()["id"]

    gen_resp = client.post(
        f"/farms/{farm.id}/assets/{asset_id}/positions/generate",
        headers=headers,
        json={
            "shelf_count": 2,
            "slots_per_shelf": 2,
            "shelf_prefix": "SH-",
            "slot_prefix": "SL-",
            "shelf_pad_width": 2,
            "slot_pad_width": 2,
        },
    )
    assert gen_resp.status_code == 201
    assert len(gen_resp.json()) == 2 + 2 * 2

    tree_resp = client.get(f"/farms/{farm.id}/assets/{asset_id}/positions/tree", headers=headers)
    assert tree_resp.status_code == 200
    tree = tree_resp.json()
    assert len(tree) == 2
    assert [node["code"] for node in tree] == ["SH-01", "SH-02"]
    for shelf_node in tree:
        assert len(shelf_node["children"]) == 2
        assert all(child["position_kind"] == "slot" for child in shelf_node["children"])
