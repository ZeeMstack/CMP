"""Shared, non-collected scenario helper for VINES-OPS-003 tests. Builds on
top of VINES-OPS-001B/002's own proven `_vines_production_scenario.build_
vines_production_ready_scenario` + a real, committed `vines_production_
transfer_service.record_vines_production_transfer`, giving a real Vines
Production Batch with living plants placed under one Grow Gutter, ready to
harvest. Not a test file itself (pytest's default `test_*.py` discovery
glob does not match this name)."""
import uuid
from datetime import timedelta

from app.services import vines_production_transfer_service
from tests._vines_production_scenario import build_vines_production_ready_scenario


def build_vines_harvest_ready_scenario(
    db_session, tenant, user, farm, *, suffix=None, intervines_plant_count=4,
    grow_bag_capacity=2, grow_bag_count=10, gutter_bag_positions=20,
):
    """Returns a dict with a real Vines Production Batch, one Grow Gutter
    (`s["grow_gutter_id"]`) carrying `intervines_plant_count` living plants
    across `grow_bag_count` Grow Bags (capacity `grow_bag_capacity` each),
    and `s["harvest_time"]` (safely after both the InterVines transplant and
    the Vines Production transfer's own effective times)."""
    s = build_vines_production_ready_scenario(
        db_session, tenant, user, farm, suffix=suffix, intervines_plant_count=intervines_plant_count,
        grow_bag_capacity=grow_bag_capacity, grow_bag_count=grow_bag_count, gutter_bag_positions=gutter_bag_positions,
    )
    transfer_time = s["entry_time"] + timedelta(hours=2)
    transfer = vines_production_transfer_service.record_vines_production_transfer(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, batch_id=s["batch"].id,
        client_command_id=uuid.uuid4(), effective_time=transfer_time, note=None,
        source_intervines_table_id=s["intervines_table_id"], plant_count=intervines_plant_count,
        destination_grow_gutter_id=s["grow_gutter_id"], grow_bag_specification_id=s["grow_bag_specification"].id,
    )
    s["transfer"] = transfer
    s["harvest_time"] = transfer_time + timedelta(hours=1)
    return s
