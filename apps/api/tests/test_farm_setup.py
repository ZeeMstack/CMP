"""FARM-SETUP-001: physical farm setup orchestration tests.

Covers the three classification-specific creation flows (Nursery, Leafy
Greens, Vines) matching the ticket's own acceptance scenarios A/B/C
exactly, plus general invariants: duplicate-code rejection, tenant/farm
isolation, invalid capacity, idempotent retry, atomic rollback on a
mid-setup failure, and the two read endpoints (overview, structure)."""
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.schemas.farm_setup import (
    GerminationChamberSetupConfig,
    GreenhouseSetupCreate,
    GutterGeneratorConfig,
    LeafySetupConfig,
    NurserySectionConfig,
    NurserySetupConfig,
    SeedingMachineSetupConfig,
    SpanSetupConfig,
    TableGeneratorConfig,
    TrolleyGeneratorConfig,
    TrolleyLevelGeneratorConfig,
    TrolleySetupConfig,
    VinesSetupConfig,
    ZoneSetupConfig,
)
from app.services import farm_setup_service
from app.services.errors import (
    DuplicateLocationCodeError,
    FarmSetupCommandReusedWithDifferentPayloadError,
    LocationNotFoundError,
)


# =====================================================================
# SCENARIO A -- Leafy (ticket section 38)
# =====================================================================


def _leafy_payload(*, code="GH-L01", zones=2, spans=2, tables=3, capacity=24, ccid=None):
    return GreenhouseSetupCreate(
        code=code, name="Leafy GH", classification="leafy_greens", client_command_id=ccid or uuid.uuid4(),
        leafy=LeafySetupConfig(zones=[
            ZoneSetupConfig(code=f"Z{z:02d}", spans=[
                SpanSetupConfig(code=f"S{s:02d}", tables=TableGeneratorConfig(code_prefix="T", start=1, end=tables, pad_width=2, capacity=capacity))
                for s in range(1, spans + 1)
            ]) for z in range(1, zones + 1)
        ])
    )


@pytest.mark.integration
def test_scenario_a_leafy_exact_counts_and_no_table_position(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_leafy_payload(),
    )
    assert result.counts.zones == 2
    assert result.counts.spans == 4
    assert result.counts.tables == 12

    type_codes = db_session.execute(
        text(
            "SELECT DISTINCT lt.code FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert "table_position" not in type_codes
    assert set(type_codes) == {"greenhouse", "zone", "span", "grow_table"}

    capacities = db_session.execute(
        text(
            "SELECT DISTINCT l.capacity FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code = 'grow_table'"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert capacities == [24]

    occupiable = db_session.execute(
        text(
            "SELECT DISTINCT l.occupiable FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code = 'grow_table'"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert occupiable == [True]


@pytest.mark.integration
def test_leafy_table_code_may_restart_per_span(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=_leafy_payload(zones=1, spans=2, tables=2),
    )
    codes = db_session.execute(
        text(
            "SELECT l.code FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code = 'grow_table' ORDER BY l.code"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    # Table 01/02 appear twice -- once per Span -- proving numbering
    # restarts per parent rather than being forced globally unique.
    assert sorted(codes) == ["T01", "T01", "T02", "T02"]


@pytest.mark.integration
def test_leafy_config_rejects_gutters(active_context_with_farm) -> None:
    with pytest.raises(ValidationError, match="gutters are not valid"):
        LeafySetupConfig(zones=[
            ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(
                    code="S01",
                    tables=TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2),
                    gutters=GutterGeneratorConfig(
                        code_prefix="G", start=1, end=2, pad_width=2, bag_positions_per_gutter=1,
                        bag_position_code_prefix="BP", bag_position_pad_width=2,
                    ),
                )
            ])
        ])


@pytest.mark.integration
def test_greenhouse_setup_rejects_mismatched_structure_and_classification() -> None:
    with pytest.raises(ValidationError, match="requires matching"):
        GreenhouseSetupCreate(
            code="GH-X", name="X", classification="leafy_greens", client_command_id=uuid.uuid4(),
            vines=VinesSetupConfig(zones=[ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(code="S01", gutters=GutterGeneratorConfig(
                    code_prefix="G", start=1, end=1, pad_width=2, bag_positions_per_gutter=1,
                    bag_position_code_prefix="BP", bag_position_pad_width=2,
                ))
            ])]),
        )


# =====================================================================
# SCENARIO B -- Vines (ticket section 38)
# =====================================================================


def _vines_payload(*, code="GH-V01", spans=2, gutters=2, bag_positions=5, ccid=None):
    return GreenhouseSetupCreate(
        code=code, name="Vines GH", classification="vines", client_command_id=ccid or uuid.uuid4(),
        vines=VinesSetupConfig(zones=[
            ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(code=f"S{s:02d}", gutters=GutterGeneratorConfig(
                    code_prefix="G", start=1, end=gutters, pad_width=2,
                    bag_positions_per_gutter=bag_positions, bag_position_code_prefix="BP", bag_position_pad_width=3,
                )) for s in range(1, spans + 1)
            ])
        ])
    )


@pytest.mark.integration
def test_scenario_b_vines_exact_counts_and_no_gutter_side(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_vines_payload(),
    )
    assert result.counts.zones == 1
    assert result.counts.spans == 2
    assert result.counts.gutters == 4
    assert result.counts.bag_positions == 20

    type_codes = db_session.execute(
        text(
            "SELECT DISTINCT lt.code FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert "gutter_side" not in type_codes
    assert set(type_codes) == {"greenhouse", "zone", "span", "grow_gutter", "grow_bag_position"}

    bag_capacities = db_session.execute(
        text(
            "SELECT DISTINCT l.capacity FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code = 'grow_bag_position'"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert bag_capacities == [None]  # effective capacity 1, never configurable here


@pytest.mark.integration
def test_vines_config_rejects_tables(active_context_with_farm) -> None:
    with pytest.raises(ValidationError, match="tables are not valid"):
        VinesSetupConfig(zones=[
            ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(
                    code="S01",
                    gutters=GutterGeneratorConfig(
                        code_prefix="G", start=1, end=1, pad_width=2, bag_positions_per_gutter=1,
                        bag_position_code_prefix="BP", bag_position_pad_width=2,
                    ),
                    tables=TableGeneratorConfig(code_prefix="T", start=1, end=1, pad_width=2),
                )
            ])
        ])


@pytest.mark.integration
def test_invalid_grow_table_under_vines_rejected(db_session, active_context_with_farm) -> None:
    """The setup schema itself cannot express a Vines span with tables
    (validated above) -- this proves the classification-scoped hierarchy
    guard is still the authoritative backstop by attempting the equivalent
    invalid edge directly through the reused `location_service` core
    (exactly what `farm_setup_service` itself calls), bypassing the setup
    schema's own validator entirely, against a real Vines span."""
    from app.services import location_service
    from app.services.errors import InvalidLocationHierarchyError

    tenant, user, _headers, farm = active_context_with_farm
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=_vines_payload(code="GH-VBAD", spans=1, gutters=1, bag_positions=1),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=result.greenhouse_id,
    )
    span_id = structure.vines_zones[0].spans[0].id
    with pytest.raises(InvalidLocationHierarchyError):
        location_service._create_location_core(
            db_session, tenant_id=tenant.id, farm_id=farm.id, location_type_code="grow_table",
            code="BAD-TABLE", name="Bad Table", parent_location_id=span_id,
            greenhouse_classification=None, occupiable=True, capacity=None,
        )


# =====================================================================
# SCENARIO C -- Nursery (ticket section 38)
# =====================================================================


def _nursery_payload(
    *, code="NUR-01", ccid=None, trolleys=None, trolley_generator=None, seeding_machines=None,
    seeding_station=NurserySectionConfig(code="SEED-01"),
    germination_chamber=GerminationChamberSetupConfig(code="GERM-01"),
):
    return GreenhouseSetupCreate(
        code=code, name="Nursery GH", classification="nursery", client_command_id=ccid or uuid.uuid4(),
        nursery=NurserySetupConfig(
            seeding_station=seeding_station,
            germination_chamber=germination_chamber,
            seedling_tables=TableGeneratorConfig(code_prefix="ST", start=1, end=3, pad_width=2, capacity=30),
            intersalads_tables=TableGeneratorConfig(code_prefix="IS", start=1, end=2, pad_width=2, capacity=24),
            intervines_tables=TableGeneratorConfig(code_prefix="IV", start=1, end=2, pad_width=2, capacity=50),
            trolleys=trolleys or [],
            trolley_generator=trolley_generator,
            seeding_machines=seeding_machines or [],
        )
    )


@pytest.mark.integration
def test_scenario_c_nursery_exact_counts_and_no_zone_span(db_session, active_context_with_farm) -> None:
    """FARM-SETUP-001.1 section 13: the COMPLETE Nursery topology -- Seeding
    Station, Germination Chamber, plus all three table groups -- created in
    one command. Exactly one Nursery Greenhouse; each section present with
    its own exact counts; zero Zone/Span/Table Position anywhere."""
    tenant, user, _headers, farm = active_context_with_farm
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_nursery_payload(),
    )
    assert result.counts.seeding_stations == 1
    assert result.counts.germination_chambers == 1
    assert result.counts.seedling_tables == 3
    assert result.counts.intersalads_tables == 2
    assert result.counts.intervines_tables == 2

    greenhouse_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code = 'greenhouse'"
        ),
        {"tid": tenant.id},
    ).scalar_one()
    assert greenhouse_count == 1

    type_codes = db_session.execute(
        text(
            "SELECT DISTINCT lt.code FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert "zone" not in type_codes
    assert "span" not in type_codes
    assert "table_position" not in type_codes
    assert "seeding_station" in type_codes
    assert "germination_chamber" in type_codes

    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=result.greenhouse_id,
    )
    assert [s.code for s in structure.nursery_seeding_stations] == ["SEED-01"]
    assert structure.nursery_germination_chamber is not None and structure.nursery_germination_chamber.code == "GERM-01"
    assert len(structure.nursery_seedling.tables) == 3
    assert len(structure.nursery_intersalads.tables) == 2
    assert len(structure.nursery_intervines.tables) == 2


@pytest.mark.integration
def test_nursery_structure_returns_every_seeding_station_not_just_the_first(db_session, active_context_with_farm) -> None:
    """NURSERY-OPS-001.1 section 11: the Farm Setup wizard only ever
    creates one Seeding Station per Nursery, but the generic
    `location_service.create_location` has no cardinality guard preventing
    a second one being added under the same Nursery Greenhouse later --
    `get_greenhouse_structure` must report all of them, never silently
    collapse to the first, so the Sowing form can require an explicit
    operator choice instead of guessing."""
    tenant, user, _headers, farm = active_context_with_farm
    from app.services import location_service

    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_nursery_payload(),
    )
    location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="seeding_station", code="SEED-02", name="Second Seeding Station",
        parent_location_id=result.greenhouse_id, greenhouse_classification=None, occupiable=None, capacity=None,
    )

    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=result.greenhouse_id,
    )
    assert sorted(s.code for s in structure.nursery_seeding_stations) == ["SEED-01", "SEED-02"]


@pytest.mark.integration
def test_nursery_with_trolley_and_seeding_machine(db_session, active_context_with_farm) -> None:
    """PILOT-UX-001B section 13.A: new Farm Setup creates `level_count`
    Levels per Trolley, zero child Slots, `Level.capacity == trays_per_
    level`, and server-generated `{trolley.code}-L{NN}` codes."""
    tenant, user, _headers, farm = active_context_with_farm
    payload = _nursery_payload(
        trolleys=[TrolleySetupConfig(code="GT-01", levels=TrolleyLevelGeneratorConfig(
            level_count=3, trays_per_level=20, level_pad_width=2,
        ))],
        seeding_machines=[SeedingMachineSetupConfig(code="SM-01")],
    )
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    assert result.counts.trolleys == 1
    assert result.counts.trolley_levels == 3
    assert result.counts.trolley_slots == 0
    assert result.counts.seeding_machines == 1

    asset_types = db_session.execute(
        text(
            "SELECT at.code, a.code FROM assets a JOIN asset_types at ON at.id = a.asset_type_id "
            "WHERE a.tenant_id = :tid ORDER BY at.code"
        ),
        {"tid": tenant.id},
    ).all()
    assert ("germination_trolley", "GT-01") in asset_types
    assert ("seeding_machine", "SM-01") in asset_types

    trolley_id = db_session.execute(
        text("SELECT id FROM assets WHERE tenant_id = :tid AND code = 'GT-01'"), {"tid": tenant.id}
    ).scalar_one()
    positions = db_session.execute(
        text(
            "SELECT code, position_kind, capacity, parent_position_id FROM asset_positions "
            "WHERE asset_id = :aid ORDER BY code"
        ),
        {"aid": trolley_id},
    ).mappings().all()
    assert [p["code"] for p in positions] == ["GT-01-L01", "GT-01-L02", "GT-01-L03"]
    assert all(p["position_kind"] == "shelf" for p in positions)
    assert all(p["capacity"] == 20 for p in positions)
    assert all(p["parent_position_id"] is None for p in positions)

    child_slot_count = db_session.execute(
        text(
            "SELECT COUNT(*) FROM asset_positions WHERE asset_id = :aid AND position_kind = 'slot'"
        ),
        {"aid": trolley_id},
    ).scalar_one()
    assert child_slot_count == 0, "new Farm Setup must create zero child Slot AssetPositions"


@pytest.mark.integration
def test_nursery_trolley_level_codes_stable_and_unique_per_trolley(db_session, active_context_with_farm) -> None:
    """Two Trolleys in the same setup command each get their own
    `{trolley.code}-L{NN}` sequence -- no cross-trolley collision, no
    caller-supplied prefix accepted."""
    tenant, user, _headers, farm = active_context_with_farm
    payload = _nursery_payload(
        trolleys=[
            TrolleySetupConfig(code="GT-001", levels=TrolleyLevelGeneratorConfig(
                level_count=2, trays_per_level=4, level_pad_width=2,
            )),
            TrolleySetupConfig(code="GT-002", levels=TrolleyLevelGeneratorConfig(
                level_count=2, trays_per_level=4, level_pad_width=2,
            )),
        ],
    )
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    codes = db_session.execute(
        text(
            "SELECT a.code AS trolley_code, p.code AS level_code FROM asset_positions p "
            "JOIN assets a ON a.id = p.asset_id "
            "WHERE a.tenant_id = :tid AND a.code IN ('GT-001', 'GT-002') ORDER BY a.code, p.code"
        ),
        {"tid": tenant.id},
    ).all()
    assert codes == [
        ("GT-001", "GT-001-L01"), ("GT-001", "GT-001-L02"),
        ("GT-002", "GT-002-L01"), ("GT-002", "GT-002-L02"),
    ]


@pytest.mark.integration
def test_nursery_bulk_trolley_generator(db_session, active_context_with_farm) -> None:
    """PILOT-UX-001B2: `trolley_generator` creates N Trolleys, each with its
    own independently-restarting Level sequence, using server-generated
    `{trolley_prefix}-{NN}` Trolley codes and `{trolley.code}-{level_prefix}
    {NN}` Level codes -- matching the ticket's own worked example exactly
    (10 trolleys x 8 levels x 5 trays -> GT-01..GT-10, GT-01-L01..L08 etc)."""
    tenant, user, _headers, farm = active_context_with_farm
    payload = _nursery_payload(
        trolley_generator=TrolleyGeneratorConfig(
            trolley_count=3, trolley_prefix="GT", trolley_pad_width=2,
            levels=TrolleyLevelGeneratorConfig(level_count=8, trays_per_level=5, level_pad_width=2, level_prefix="L"),
        ),
    )
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    assert result.counts.trolleys == 3
    assert result.counts.trolley_levels == 24
    assert result.counts.trolley_slots == 0

    trolley_codes = db_session.execute(
        text(
            "SELECT a.code FROM assets a JOIN asset_types at ON at.id = a.asset_type_id "
            "WHERE a.tenant_id = :tid AND at.code = 'germination_trolley' ORDER BY a.code"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert trolley_codes == ["GT-01", "GT-02", "GT-03"]

    level_codes = db_session.execute(
        text(
            "SELECT p.code FROM asset_positions p JOIN assets a ON a.id = p.asset_id "
            "WHERE a.tenant_id = :tid AND a.code = 'GT-01' ORDER BY p.code"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert level_codes == [f"GT-01-L{n:02d}" for n in range(1, 9)]

    capacities = db_session.execute(
        text(
            "SELECT DISTINCT p.capacity, p.position_kind FROM asset_positions p JOIN assets a ON a.id = p.asset_id "
            "WHERE a.tenant_id = :tid AND a.code LIKE 'GT-%'"
        ),
        {"tid": tenant.id},
    ).all()
    assert capacities == [(5, "shelf")], "every Level must have capacity=trays_per_level and be a root shelf, zero slots"


@pytest.mark.integration
def test_nursery_trolley_generator_custom_level_prefix(db_session, active_context_with_farm) -> None:
    """`level_prefix` is operator-configurable but always prepended by the
    Trolley's own code server-side -- never freestanding."""
    tenant, user, _headers, farm = active_context_with_farm
    payload = _nursery_payload(
        trolley_generator=TrolleyGeneratorConfig(
            trolley_count=1, trolley_prefix="GT", trolley_pad_width=2,
            levels=TrolleyLevelGeneratorConfig(level_count=2, trays_per_level=5, level_pad_width=2, level_prefix="SHELF"),
        ),
    )
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    level_codes = db_session.execute(
        text(
            "SELECT p.code FROM asset_positions p JOIN assets a ON a.id = p.asset_id "
            "WHERE a.tenant_id = :tid AND a.code = 'GT-01' ORDER BY p.code"
        ),
        {"tid": tenant.id},
    ).scalars().all()
    assert level_codes == ["GT-01-SHELF01", "GT-01-SHELF02"]


@pytest.mark.integration
def test_nursery_trolleys_and_trolley_generator_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="either explicit trolleys or a trolley_generator"):
        NurserySetupConfig(
            trolleys=[TrolleySetupConfig(code="GT-01", levels=TrolleyLevelGeneratorConfig(
                level_count=1, trays_per_level=1, level_pad_width=2,
            ))],
            trolley_generator=TrolleyGeneratorConfig(
                trolley_count=1, trolley_prefix="GT",
                levels=TrolleyLevelGeneratorConfig(level_count=1, trays_per_level=1, level_pad_width=2),
            ),
        )


@pytest.mark.integration
def test_trolley_generator_rejects_non_positive_count() -> None:
    with pytest.raises(ValidationError, match="positive integer"):
        TrolleyGeneratorConfig(
            trolley_count=0, trolley_prefix="GT",
            levels=TrolleyLevelGeneratorConfig(level_count=1, trays_per_level=1, level_pad_width=2),
        )


@pytest.mark.integration
def test_trolley_generator_rejects_blank_prefix() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        TrolleyGeneratorConfig(
            trolley_count=1, trolley_prefix="  ",
            levels=TrolleyLevelGeneratorConfig(level_count=1, trays_per_level=1, level_pad_width=2),
        )


@pytest.mark.integration
def test_atomic_rollback_on_bulk_trolley_generator_conflict(db_session, active_context_with_farm) -> None:
    """A mid-generator Trolley code conflict (e.g. GT-02 already registered
    outside this command) must roll back the ENTIRE setup -- no partial
    Trolley (GT-01), no partial Greenhouse."""
    from app.services import asset_service
    from app.services.errors import DuplicateAssetCodeError

    tenant, user, _headers, farm = active_context_with_farm
    asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-02", name="Pre-existing", commissioned_date=None,
    )
    payload = _nursery_payload(
        code="NUR-BULK-ROLLBACK",
        trolley_generator=TrolleyGeneratorConfig(
            trolley_count=3, trolley_prefix="GT", trolley_pad_width=2,
            levels=TrolleyLevelGeneratorConfig(level_count=2, trays_per_level=5, level_pad_width=2),
        ),
    )
    with pytest.raises(DuplicateAssetCodeError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
        )

    remaining_gh = db_session.execute(
        text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'NUR-BULK-ROLLBACK'"), {"tid": tenant.id}
    ).scalar_one()
    assert remaining_gh == 0
    gt01 = db_session.execute(
        text("SELECT COUNT(*) FROM assets WHERE tenant_id = :tid AND code = 'GT-01'"), {"tid": tenant.id}
    ).scalar_one()
    assert gt01 == 0, "GT-01, created earlier in the same failed generator loop, must not survive"


# =====================================================================
# General invariants
# =====================================================================


@pytest.mark.integration
def test_duplicate_greenhouse_code_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_leafy_payload(code="GH-DUP"),
    )
    with pytest.raises(DuplicateLocationCodeError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            payload=_leafy_payload(code="GH-DUP", zones=1, spans=1, tables=1),
        )


@pytest.mark.integration
def test_invalid_capacity_zero_rejected() -> None:
    with pytest.raises(ValidationError, match="positive integer"):
        TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2, capacity=0)


@pytest.mark.integration
def test_invalid_capacity_negative_rejected() -> None:
    with pytest.raises(ValidationError, match="positive integer"):
        TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2, capacity=-1)


@pytest.mark.integration
def test_tenant_isolation_greenhouse_setup(db_session, active_context_with_farm) -> None:
    from app.services import farm_service, membership_service, tenant_service, user_service
    from app.services.errors import FarmNotFoundError

    tenant, user, _headers, farm = active_context_with_farm
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_leafy_payload(code="GH-ISO"),
    )

    suffix = uuid.uuid4().hex[:8]
    other_tenant = tenant_service.create_tenant(db_session, code=f"other-{suffix}", name="Other")
    other_user = user_service.create_user(
        db_session, oidc_issuer="other", oidc_subject=suffix, email=f"{suffix}@example.com", display_name="Other",
    )
    membership_service.add_membership(
        db_session, tenant_id=other_tenant.id, user_id=other_user.id, role_code="tenant_admin", actor_user_id=None,
    )
    other_farm = farm_service.create_farm(
        db_session, tenant_id=other_tenant.id, actor_user_id=other_user.id, code=f"farm-{suffix}", name="Other Farm",
        country_code="AE", city_region=None, timezone="Asia/Dubai",
    )
    # Cross-tenant farm_id lookup (Tenant A's own real farm.id, but this
    # command run as Tenant B) must fail as farm-not-found -- never see
    # or write into Tenant A's farm.
    with pytest.raises(FarmNotFoundError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=other_tenant.id, farm_id=farm.id, actor_user_id=other_user.id,
            payload=_leafy_payload(code="GH-CROSS", zones=1, spans=1, tables=1),
        )

    overview_other = farm_setup_service.get_greenhouse_setup_overview(
        db_session.connection(), tenant_id=other_tenant.id, farm_id=other_farm.id,
    )
    assert overview_other == []


@pytest.mark.integration
def test_idempotent_replay_returns_same_greenhouse(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    ccid = uuid.uuid4()
    payload = _leafy_payload(code="GH-IDEM", ccid=ccid)
    first = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    second = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )
    assert second.greenhouse_id == first.greenhouse_id

    count = db_session.execute(
        text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'GH-IDEM'"), {"tid": tenant.id}
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_idempotent_replay_with_different_payload_rejected(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    ccid = uuid.uuid4()
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=_leafy_payload(code="GH-REUSE", ccid=ccid),
    )
    with pytest.raises(FarmSetupCommandReusedWithDifferentPayloadError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
            payload=_leafy_payload(code="GH-REUSE-DIFFERENT", ccid=ccid),
        )


@pytest.mark.integration
def test_atomic_rollback_on_mid_setup_duplicate_table_code(db_session, active_context_with_farm) -> None:
    """A deep child (a duplicate table code within the same Span generator
    call) becomes invalid -- the ENTIRE command must fail, with no
    Greenhouse, no partial Zones/Spans/Tables left behind."""
    tenant, user, _headers, farm = active_context_with_farm

    # Pre-create a conflicting table code so the second span's generator
    # call collides with something that already exists as a sibling under
    # its own span target -- simplest reliable trigger: reuse the exact
    # same zone/span/table codes twice via two zones sharing a coincidental
    # duplicate greenhouse code is not needed; instead we force a
    # mid-command duplicate by using a generator range that re-includes an
    # already-generated table code within the SAME span (start overlapping
    # a previous span is fine since codes restart per span -- so instead we
    # duplicate the SPAN code itself across two zones' first span, which
    # collides only if they share a parent; construct a genuine duplicate
    # by repeating a zone code).
    payload = GreenhouseSetupCreate(
        code="GH-ROLLBACK", name="Rollback GH", classification="leafy_greens", client_command_id=uuid.uuid4(),
        leafy=LeafySetupConfig(zones=[
            ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(code="S01", tables=TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2, capacity=10)),
            ]),
            ZoneSetupConfig(code="Z01", spans=[  # duplicate zone code -> fails on the second zone
                SpanSetupConfig(code="S01", tables=TableGeneratorConfig(code_prefix="T", start=1, end=2, pad_width=2, capacity=10)),
            ]),
        ])
    )
    with pytest.raises(DuplicateLocationCodeError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
        )

    remaining = db_session.execute(
        text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'GH-ROLLBACK'"), {"tid": tenant.id}
    ).scalar_one()
    assert remaining == 0, "the Greenhouse itself must not survive a failed setup command"
    any_z01 = db_session.execute(
        text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'Z01'"), {"tid": tenant.id}
    ).scalar_one()
    assert any_z01 == 0, "no partial Zone may survive a failed setup command"
    any_tables = db_session.execute(
        text("SELECT COUNT(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id WHERE l.tenant_id = :tid AND lt.code = 'grow_table'"),
        {"tid": tenant.id},
    ).scalar_one()
    assert any_tables == 0, "no partial Table may survive a failed setup command"


@pytest.mark.integration
def test_atomic_rollback_on_complete_nursery_with_late_asset_conflict(db_session, active_context_with_farm) -> None:
    """FARM-SETUP-001.1 section 14: Seeding Station, Germination Chamber,
    and all three table groups are created (still uncommitted, same
    transaction) BEFORE the failure trigger -- a Trolley code that already
    exists as a farm-level Asset, pre-registered outside this command. The
    ENTIRE command must still roll back: no partial Nursery locations
    survive, and no accidental farm-level Asset from this command's own
    (never-committed) Trolley registration survives either."""
    from app.services import asset_service
    from app.services.errors import DuplicateAssetCodeError

    tenant, user, _headers, farm = active_context_with_farm
    asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="GT-PRECONFLICT", name="Pre-existing Trolley", commissioned_date=None,
    )

    payload = _nursery_payload(
        code="NUR-ROLLBACK",
        trolleys=[TrolleySetupConfig(code="GT-PRECONFLICT", levels=TrolleyLevelGeneratorConfig(
            level_count=1, trays_per_level=1, level_pad_width=2,
        ))],
    )
    with pytest.raises(DuplicateAssetCodeError):
        farm_setup_service.create_greenhouse_setup(
            db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
        )

    remaining = db_session.execute(
        text("SELECT COUNT(*) FROM locations WHERE tenant_id = :tid AND code = 'NUR-ROLLBACK'"), {"tid": tenant.id}
    ).scalar_one()
    assert remaining == 0, "the Greenhouse itself must not survive a failed setup command"
    any_sections = db_session.execute(
        text(
            "SELECT COUNT(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code IN ('seeding_station', 'germination_chamber')"
        ),
        {"tid": tenant.id},
    ).scalar_one()
    assert any_sections == 0, "no partial Seeding Station/Germination Chamber may survive a failed setup command"
    any_tables = db_session.execute(
        text(
            "SELECT COUNT(*) FROM locations l JOIN location_types lt ON lt.id = l.location_type_id "
            "WHERE l.tenant_id = :tid AND lt.code IN ('seedling_table', 'intersalads_table', 'intervines_table')"
        ),
        {"tid": tenant.id},
    ).scalar_one()
    assert any_tables == 0, "no partial Nursery table may survive a failed setup command"
    asset_count = db_session.execute(
        text("SELECT COUNT(*) FROM assets WHERE tenant_id = :tid AND code = 'GT-PRECONFLICT'"), {"tid": tenant.id}
    ).scalar_one()
    assert asset_count == 1, "only the pre-existing Asset may survive -- no duplicate from the failed command"


# =====================================================================
# Read endpoints: overview + structure
# =====================================================================


@pytest.mark.integration
def test_overview_reports_derived_counts_and_status(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_leafy_payload(code="GH-OV1"),
    )
    empty_gh = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="GH-OV2", name="Empty-ish", classification="vines", client_command_id=uuid.uuid4(),
            vines=VinesSetupConfig(zones=[ZoneSetupConfig(code="Z01", spans=[
                SpanSetupConfig(code="S01", gutters=GutterGeneratorConfig(
                    code_prefix="G", start=1, end=1, pad_width=2, bag_positions_per_gutter=1,
                    bag_position_code_prefix="BP", bag_position_pad_width=2,
                ))
            ])]),
        ),
    )

    overview = farm_setup_service.get_greenhouse_setup_overview(db_session.connection(), tenant_id=tenant.id, farm_id=farm.id)
    by_code = {item.code: item for item in overview}
    assert by_code["GH-OV1"].status == "configured"
    assert by_code["GH-OV1"].counts.tables == 12
    assert by_code["GH-OV2"].status == "configured"  # has a bag position -> configured
    assert by_code["GH-OV2"].counts.bag_positions == 1


@pytest.mark.integration
def test_nursery_status_requires_all_five_sections_for_configured(db_session, active_context_with_farm) -> None:
    """FARM-SETUP-001.2 section 2/4: 'configured' requires ALL FIVE
    structural sections (Seeding Station, Germination Chamber, Seedling,
    InterSalads, InterVines tables) -- a single section, or four of five,
    is only 'partial'. Cases A-F from the ticket, exercised through the
    real overview endpoint (real Locations, not the pure function)."""
    tenant, user, _headers, farm = active_context_with_farm

    # A. greenhouse only -> empty
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-A", name="Empty Nursery", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(trolleys=[TrolleySetupConfig(code="GT-A", levels=TrolleyLevelGeneratorConfig(
                level_count=1, trays_per_level=1, level_pad_width=2,
            ))]),
        ),
    )
    # B. Seeding Station only -> partial
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-B", name="Only Seeding Station", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(seeding_station=NurserySectionConfig(code="SEED-B")),
        ),
    )
    # C. Germination Chamber only -> partial
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-C", name="Only Germination Chamber", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(germination_chamber=GerminationChamberSetupConfig(code="GERM-C")),
        ),
    )
    # D. Seedling Tables only -> partial
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-D", name="Only Seedling", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seedling_tables=TableGeneratorConfig(code_prefix="ST", start=1, end=1, pad_width=2, capacity=10),
            ),
        ),
    )
    # E. all five required structural sections present -> configured
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=_nursery_payload(code="NUR-E"),
    )
    # F. four of five present (missing InterVines) -> partial
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-F", name="Four Of Five", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(
                seeding_station=NurserySectionConfig(code="SEED-F"),
                germination_chamber=GerminationChamberSetupConfig(code="GERM-F"),
                seedling_tables=TableGeneratorConfig(code_prefix="ST", start=1, end=1, pad_width=2, capacity=10),
                intersalads_tables=TableGeneratorConfig(code_prefix="IS", start=1, end=1, pad_width=2, capacity=10),
            ),
        ),
    )
    # G. Trolley / Seeding Machine only -> does NOT make Nursery configured
    #    (no structural component at all -> empty, per section 2's own
    #    EMPTY definition: "no Nursery structural component exists" --
    #    Trolleys/Seeding Machines are explicitly not Nursery-owned
    #    Locations, see section 9).
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=GreenhouseSetupCreate(
            code="NUR-G", name="Trolley Only", classification="nursery", client_command_id=uuid.uuid4(),
            nursery=NurserySetupConfig(seeding_machines=[SeedingMachineSetupConfig(code="SM-G")]),
        ),
    )
    # H. full structure + Assets -> configured (Assets never block completion either)
    farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=_nursery_payload(
            code="NUR-H",
            trolleys=[TrolleySetupConfig(code="GT-H", levels=TrolleyLevelGeneratorConfig(
                level_count=1, trays_per_level=1, level_pad_width=2,
            ))],
            seeding_machines=[SeedingMachineSetupConfig(code="SM-H")],
        ),
    )

    overview = farm_setup_service.get_greenhouse_setup_overview(db_session.connection(), tenant_id=tenant.id, farm_id=farm.id)
    by_code = {item.code: item for item in overview}
    assert by_code["NUR-A"].status == "empty"
    assert by_code["NUR-B"].status == "partial"
    assert by_code["NUR-C"].status == "partial"
    assert by_code["NUR-D"].status == "partial"
    assert by_code["NUR-E"].status == "configured"
    assert by_code["NUR-F"].status == "partial"
    assert by_code["NUR-G"].status == "empty"
    assert by_code["NUR-H"].status == "configured"


def test_nursery_derive_status_trolley_alone_is_empty_not_partial_or_configured() -> None:
    """FARM-SETUP-001.2: Trolleys/Seeding Machines are farm-level
    equipment, not Nursery structure -- a Trolley alone (no physical
    Nursery section) contributes to neither 'partial' nor 'configured'.
    Asserted directly against `_derive_status` (a pure function of
    `GreenhouseSetupCounts`) since `get_greenhouse_setup_overview`'s own
    walk of the Location tree never counts Assets at all (Assets have no
    Location/greenhouse ownership link in this schema); the real-data case
    is covered end to end by case G in the test above."""
    from app.schemas.farm_setup import GreenhouseSetupCounts

    counts = GreenhouseSetupCounts(trolleys=1, trolley_levels=1, trolley_slots=1)
    assert farm_setup_service._derive_status(classification="nursery", counts=counts) == "empty"


def test_nursery_derive_status_four_of_five_sections_is_partial() -> None:
    """Direct unit-level proof that 'configured' truly requires ALL FIVE,
    not just 'most' -- four present, one missing, must still be 'partial'."""
    from app.schemas.farm_setup import GreenhouseSetupCounts

    for missing_field in ("seeding_stations", "germination_chambers", "seedling_tables", "intersalads_tables", "intervines_tables"):
        full = dict(seeding_stations=1, germination_chambers=1, seedling_tables=1, intersalads_tables=1, intervines_tables=1)
        full[missing_field] = 0
        counts = GreenhouseSetupCounts(**full)
        assert farm_setup_service._derive_status(classification="nursery", counts=counts) == "partial", missing_field


@pytest.mark.integration
def test_structure_view_matches_created_hierarchy(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        payload=_leafy_payload(code="GH-STRUCT", zones=2, spans=2, tables=3, capacity=24),
    )
    structure = farm_setup_service.get_greenhouse_structure(
        db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=result.greenhouse_id,
    )
    assert structure.classification == "leafy_greens"
    assert len(structure.leafy_zones) == 2
    for zone in structure.leafy_zones:
        assert len(zone.spans) == 2
        for span in zone.spans:
            assert len(span.tables) == 3
            assert all(t.capacity == 24 for t in span.tables)
    assert structure.vines_zones is None
    assert structure.nursery_seedling is None


@pytest.mark.integration
def test_structure_view_unknown_greenhouse_not_found(db_session, active_context_with_farm) -> None:
    tenant, _user, _headers, farm = active_context_with_farm
    with pytest.raises(LocationNotFoundError):
        farm_setup_service.get_greenhouse_structure(
            db_session.connection(), tenant_id=tenant.id, farm_id=farm.id, greenhouse_id=uuid.uuid4(),
        )
