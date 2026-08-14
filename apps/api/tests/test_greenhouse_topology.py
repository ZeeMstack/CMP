"""DOMAIN-FARM-001: classification-aware greenhouse topology tests.

Covers the ticket's required positive topology proofs (section 14),
negative topology proofs including the "no bypass via a generic rule"
proof (section 15), and greenhouse-classification value/immutability
proofs (section 16). Exercises the real `location_service` validation path
(and, for a representative case, the real HTTP API), never a raw DB insert
for the positive/negative topology assertions -- raw SQL is used only where
the ticket specifically wants a DB-layer (not application-layer) guarantee
proven (classification value CHECK, immutability trigger).
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.schemas.location import GREENHOUSE_CLASSIFICATIONS, LocationCreate
from app.services import location_service
from app.services.errors import InvalidLocationHierarchyError


def _create(db_session, tenant, farm, user, **overrides):
    defaults = dict(
        tenant_id=tenant.id,
        farm_id=farm.id,
        actor_user_id=user.id,
        parent_location_id=None,
        greenhouse_classification=None,
        occupiable=None,
    )
    defaults.update(overrides)
    return location_service.create_location(db_session, **defaults)


def _greenhouse(db_session, tenant, farm, user, *, classification: str, code: str = "gh-1"):
    return _create(
        db_session, tenant, farm, user,
        location_type_code="greenhouse", code=code, name="GH", greenhouse_classification=classification,
    )


# =====================================================================
# Section 14: positive topology proofs
# =====================================================================


@pytest.mark.integration
def test_nursery_greenhouse_accepts_seeding_station(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    station = _create(db_session, tenant, farm, user, location_type_code="seeding_station", code="seed-1", name="Seeding Station", parent_location_id=gh.id)
    assert station.parent_location_id == gh.id


@pytest.mark.integration
def test_nursery_greenhouse_accepts_germination_chamber(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    chamber = _create(db_session, tenant, farm, user, location_type_code="germination_chamber", code="gc-1", name="Chamber", parent_location_id=gh.id)
    assert chamber.parent_location_id == gh.id


@pytest.mark.integration
def test_nursery_greenhouse_accepts_seedling_area_and_table(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    area = _create(db_session, tenant, farm, user, location_type_code="seedling_area", code="sla-1", name="Seedling Area", parent_location_id=gh.id)
    table = _create(db_session, tenant, farm, user, location_type_code="seedling_table", code="slt-1", name="Seedling Table", parent_location_id=area.id)
    assert area.parent_location_id == gh.id
    assert table.parent_location_id == area.id


@pytest.mark.integration
def test_nursery_greenhouse_accepts_intersalads_and_table(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    section = _create(db_session, tenant, farm, user, location_type_code="intersalads", code="is-1", name="InterSalads", parent_location_id=gh.id)
    table = _create(db_session, tenant, farm, user, location_type_code="intersalads_table", code="ist-1", name="InterSalads Table", parent_location_id=section.id)
    assert section.parent_location_id == gh.id
    assert table.parent_location_id == section.id


@pytest.mark.integration
def test_nursery_greenhouse_accepts_intervines_and_table(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    section = _create(db_session, tenant, farm, user, location_type_code="intervines", code="iv-1", name="InterVines", parent_location_id=gh.id)
    table = _create(db_session, tenant, farm, user, location_type_code="intervines_table", code="ivt-1", name="InterVines Table", parent_location_id=section.id)
    assert section.parent_location_id == gh.id
    assert table.parent_location_id == section.id


@pytest.mark.integration
def test_leafy_greenhouse_accepts_full_exact_chain(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="leafy_greens")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    table = _create(db_session, tenant, farm, user, location_type_code="grow_table", code="table-1", name="Table", parent_location_id=span.id)
    assert zone.parent_location_id == gh.id
    assert span.parent_location_id == zone.id
    assert table.parent_location_id == span.id


@pytest.mark.integration
def test_leafy_greenhouse_full_chain_via_http_api(client, active_context_with_farm) -> None:
    """The same exact chain via the real HTTP API, not just the service
    layer directly -- proves the router/schema/service path together."""
    tenant, user, headers, farm = active_context_with_farm
    gh_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers,
        json={"location_type_code": "greenhouse", "code": "api-gh-1", "name": "GH", "greenhouse_classification": "leafy_greens"},
    ).json()["id"]
    zone_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers,
        json={"location_type_code": "zone", "code": "api-zone-1", "name": "Zone", "parent_location_id": gh_id},
    ).json()["id"]
    span_id = client.post(
        f"/farms/{farm.id}/locations", headers=headers,
        json={"location_type_code": "span", "code": "api-span-1", "name": "Span", "parent_location_id": zone_id},
    ).json()["id"]
    table_resp = client.post(
        f"/farms/{farm.id}/locations", headers=headers,
        json={"location_type_code": "grow_table", "code": "api-table-1", "name": "Table", "parent_location_id": span_id},
    )
    assert table_resp.status_code == 201, table_resp.text
    assert table_resp.json()["parent_location_id"] == span_id


@pytest.mark.integration
def test_vines_greenhouse_accepts_full_exact_chain(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    gutter = _create(db_session, tenant, farm, user, location_type_code="grow_gutter", code="gutter-1", name="Gutter", parent_location_id=span.id)
    bag_position = _create(db_session, tenant, farm, user, location_type_code="grow_bag_position", code="bp-1", name="Bag Position", parent_location_id=gutter.id)
    assert zone.parent_location_id == gh.id
    assert span.parent_location_id == zone.id
    assert gutter.parent_location_id == span.id
    assert bag_position.parent_location_id == gutter.id


# =====================================================================
# Section 15: negative topology proofs
# =====================================================================


@pytest.mark.integration
@pytest.mark.parametrize("child_type_code", ["zone", "span", "grow_gutter", "grow_bag_position"])
def test_nursery_greenhouse_rejects_production_topology(db_session, active_context_with_farm, child_type_code) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code=child_type_code, code="child-1", name="Child", parent_location_id=gh.id)


@pytest.mark.integration
def test_leafy_greenhouse_rejects_grow_gutter(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="leafy_greens")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="grow_gutter", code="gutter-1", name="Gutter", parent_location_id=span.id)


@pytest.mark.integration
def test_leafy_greenhouse_rejects_grow_bag_position_shortcut(db_session, active_context_with_farm) -> None:
    """Even directly under the greenhouse -- proves grow_bag_position is not
    reachable at all under a leafy_greens-classified tree."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="leafy_greens")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="grow_bag_position", code="bp-1", name="Bag Position", parent_location_id=gh.id)


@pytest.mark.integration
def test_leafy_greenhouse_rejects_nursery_specific_section(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="leafy_greens")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="seeding_station", code="seed-1", name="Seeding Station", parent_location_id=gh.id)


@pytest.mark.integration
def test_leafy_greenhouse_rejects_table_position_beneath_authoritative_grow_table(db_session, active_context_with_farm) -> None:
    """The single most important Leafy correction: the Production
    Cultivation Plate is a Carrier, not a Location -- table_position must
    never be a legal continuation under the authoritative grow_table."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="leafy_greens")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    table = _create(db_session, tenant, farm, user, location_type_code="grow_table", code="table-1", name="Table", parent_location_id=span.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="table_position", code="pos-1", name="Position", parent_location_id=table.id)


@pytest.mark.integration
@pytest.mark.parametrize(
    "shortcut_parent_classification,shortcut_parent_type,shortcut_child_type",
    [
        ("leafy_greens", "greenhouse", "span"),
        ("leafy_greens", "zone", "grow_table"),
        ("vines", "greenhouse", "span"),
        ("vines", "zone", "grow_gutter"),
    ],
)
def test_production_greenhouses_reject_zone_span_shortcuts(
    db_session, active_context_with_farm, shortcut_parent_classification, shortcut_parent_type, shortcut_child_type
) -> None:
    """Section 9: 'Do NOT permit shortcuts such as Greenhouse -> Span,
    Greenhouse -> Table, Zone -> Table' -- every level in the exact chain
    is mandatory, not optional, for Leafy/Vines production topology."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification=shortcut_parent_classification)
    if shortcut_parent_type == "greenhouse":
        parent = gh
    else:
        parent = _create(db_session, tenant, farm, user, location_type_code=shortcut_parent_type, code="mid-1", name="Mid", parent_location_id=gh.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code=shortcut_child_type, code="child-1", name="Child", parent_location_id=parent.id)


@pytest.mark.integration
def test_vines_greenhouse_rejects_grow_table(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="grow_table", code="table-1", name="Table", parent_location_id=span.id)


@pytest.mark.integration
def test_vines_greenhouse_rejects_table_position(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="table_position", code="pos-1", name="Position", parent_location_id=gh.id)


@pytest.mark.integration
def test_vines_greenhouse_rejects_nursery_specific_section(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="germination_chamber", code="gc-1", name="Chamber", parent_location_id=gh.id)


@pytest.mark.integration
def test_vines_greenhouse_rejects_gutter_side_as_placement(db_session, active_context_with_farm) -> None:
    """Grow Gutter Side is NOT a crop-placement location: the generic
    `grow_gutter -> gutter_side` edge still exists in the DB (untouched,
    per the ticket's instruction not to delete it), but it is not part of
    the Vines classification-scoped rule set, so it must be unreachable
    from inside a vines-classified greenhouse. Since this rejection is
    exactly what makes `gutter_side -> grow_bag_position` unreachable too
    (there is no legal way to obtain a `gutter_side` row under a
    vines-classified tree to test that second edge against), this single
    proof covers the full deprecated path."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    zone = _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    span = _create(db_session, tenant, farm, user, location_type_code="span", code="span-1", name="Span", parent_location_id=zone.id)
    gutter = _create(db_session, tenant, farm, user, location_type_code="grow_gutter", code="gutter-1", name="Gutter", parent_location_id=span.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="gutter_side", code="side-1", name="Side", parent_location_id=gutter.id)


@pytest.mark.integration
def test_classification_scoped_validation_is_not_bypassed_by_a_matching_generic_rule(
    db_session, active_context_with_farm
) -> None:
    """The decisive proof for section 5's hard requirement: the generic
    (`greenhouse_classification IS NULL`) rule table still contains
    `(greenhouse, zone)` and `(greenhouse, area)` -- untouched, exactly as
    seeded before this ticket. If classification-scoped validation ever
    silently fell back to the generic table, a `zone` (or `area`) would be
    wrongly accepted directly under a NURSERY greenhouse, since the generic
    rule technically matches that parent/child type pair. It must still be
    rejected, because Nursery's *scoped* rule set does not include either."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="zone", code="zone-1", name="Zone", parent_location_id=gh.id)
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="area", code="area-1", name="Area", parent_location_id=gh.id)


@pytest.mark.integration
def test_bulk_generate_children_also_enforces_classification_scoped_topology(
    db_session, active_context_with_farm
) -> None:
    """The classification-aware check applies identically to bulk
    generation, not just single-location creation."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    with pytest.raises(InvalidLocationHierarchyError):
        location_service.bulk_generate_children(
            db_session, tenant_id=tenant.id, farm_id=farm.id, parent_id=gh.id, actor_user_id=user.id,
            location_type_code="chamber_position", code_prefix="P", start=1, end=3, pad_width=2, name_template=None,
        )


@pytest.mark.integration
def test_generic_rules_remain_unaffected_outside_any_greenhouse(db_session, active_context_with_farm) -> None:
    """A non-greenhouse root tree (store -> store_bin) is governed purely
    by the pre-existing generic rules, exactly as before this ticket --
    classification-aware scoping only ever activates inside a greenhouse."""
    tenant, user, _headers, farm = active_context_with_farm
    store = _create(db_session, tenant, farm, user, location_type_code="store", code="store-1", name="Store")
    bin_ = _create(db_session, tenant, farm, user, location_type_code="store_bin", code="bin-1", name="Bin", parent_location_id=store.id)
    assert bin_.parent_location_id == store.id
    with pytest.raises(InvalidLocationHierarchyError):
        _create(db_session, tenant, farm, user, location_type_code="area", code="area-1", name="Area", parent_location_id=store.id)


# =====================================================================
# Section 16: greenhouse classification value + immutability proofs
# =====================================================================


@pytest.mark.integration
def test_application_accepts_only_the_three_authoritative_classifications() -> None:
    assert GREENHOUSE_CLASSIFICATIONS == frozenset({"nursery", "leafy_greens", "vines"})


@pytest.mark.integration
@pytest.mark.parametrize("value", ["mixed", "other", "unknown", ""])
def test_application_rejects_non_authoritative_classification_values_by_schema(value: str) -> None:
    with pytest.raises(ValueError):
        LocationCreate(location_type_code="greenhouse", code="GH-01", name="GH", greenhouse_classification=value)


@pytest.mark.integration
@pytest.mark.parametrize(
    "value,expected",
    [
        ("nursery", "nursery"),
        ("leafy_greens", "leafy_greens"),
        ("vines", "vines"),
        ("LEAFY_GREENS", "leafy_greens"),
        ("  vines  ", "vines"),
    ],
)
def test_application_accepts_each_authoritative_classification_value_by_schema(value: str, expected: str) -> None:
    """Case/whitespace are normalized before the value-set check (matching
    `_normalize_classification`'s existing, unchanged behavior) -- this is
    not new to DOMAIN-FARM-001, just re-pinned against the narrowed set."""
    payload = LocationCreate(location_type_code="greenhouse", code="GH-01", name="GH", greenhouse_classification=value)
    assert payload.greenhouse_classification == expected


@pytest.mark.integration
def test_db_rejects_mixed_and_other_directly(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    from app.models.location_type import LocationType
    from sqlalchemy import select

    gh_type = db_session.execute(select(LocationType).where(LocationType.code == "greenhouse")).scalar_one()
    for legacy_value in ("mixed", "other"):
        with pytest.raises(DBAPIError):
            with db_session.begin_nested():
                db_session.execute(
                    text(
                        "INSERT INTO locations (id, tenant_id, farm_id, location_type_id, code, name, "
                        "status, greenhouse_classification, occupiable) "
                        "VALUES (:id, :tenant_id, :farm_id, :type_id, :code, 'Bad', 'active', :classification, false)"
                    ),
                    {
                        "id": uuid.uuid4(), "tenant_id": tenant.id, "farm_id": farm.id, "type_id": gh_type.id,
                        "code": f"BAD-{legacy_value}", "classification": legacy_value,
                    },
                )


@pytest.mark.integration
def test_db_rejects_changing_classification_after_creation(db_session, active_context_with_farm) -> None:
    """No greenhouse-classification update API exists (deliberately, per
    the ticket) -- this proves the DB-layer immutability trigger itself,
    via a direct UPDATE, independent of there being no application path to
    reach it today."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="nursery")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE locations SET greenhouse_classification = 'leafy_greens' WHERE id = :id"),
                {"id": gh.id},
            )


@pytest.mark.integration
@pytest.mark.parametrize(
    "from_value,to_value",
    [("nursery", "leafy_greens"), ("nursery", "vines"), ("leafy_greens", "vines"), ("vines", "nursery")],
)
def test_db_rejects_every_classification_transition(db_session, active_context_with_farm, from_value, to_value) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification=from_value, code=f"gh-{from_value}-{to_value}")
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            db_session.execute(
                text("UPDATE locations SET greenhouse_classification = :to_value WHERE id = :id"),
                {"id": gh.id, "to_value": to_value},
            )


@pytest.mark.integration
def test_db_allows_a_no_op_classification_update(db_session, active_context_with_farm) -> None:
    """Setting the same value back onto itself must succeed -- the trigger
    compares NEW to OLD, not merely "is UPDATE"."""
    tenant, user, _headers, farm = active_context_with_farm
    gh = _greenhouse(db_session, tenant, farm, user, classification="vines")
    db_session.execute(
        text("UPDATE locations SET greenhouse_classification = 'vines' WHERE id = :id"),
        {"id": gh.id},
    )
    db_session.flush()
    db_session.refresh(gh)
    assert gh.greenhouse_classification == "vines"


@pytest.mark.integration
def test_non_greenhouse_location_still_requires_null_classification(db_session, active_context_with_farm) -> None:
    """`location_service.create_location` (unlike `LocationCreate`, the
    Pydantic schema) does not itself validate this -- it is enforced as a
    DB-layer backstop by the same trigger, exercised here by calling the
    service directly (bypassing the schema) with a non-null classification
    on a non-greenhouse type."""
    tenant, user, _headers, farm = active_context_with_farm
    with pytest.raises(DBAPIError):
        with db_session.begin_nested():
            _create(
                db_session, tenant, farm, user, location_type_code="store", code="store-1", name="Store",
                greenhouse_classification="nursery",
            )
