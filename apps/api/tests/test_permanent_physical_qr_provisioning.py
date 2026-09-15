"""PILOT-SCAN-001D: every permanent physical Location/Carrier/Asset gets
its permanent QR identity automatically at creation -- never a manual
"Generate QR" step, and never a duplicate active identity on retry.
Covers the ticket's required proofs 1-5 directly against the service
layer (never through the QR API routes, which are already covered by
`test_qr_authz.py`/`test_qr_scan_acceptance.py`).
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.qr_identifier import QrIdentifier
from app.services import asset_service, carrier_service, farm_setup_service, location_service, qr_service
from tests.conftest import ensure_seed_tray_specification


def _active_qr(db_session, *, tenant_id, column, entity_id):
    return db_session.execute(
        select(QrIdentifier).where(
            QrIdentifier.tenant_id == tenant_id,
            getattr(QrIdentifier, column) == entity_id,
            QrIdentifier.status == "active",
        )
    ).scalar_one_or_none()


@pytest.mark.integration
def test_creating_a_carrier_automatically_provisions_its_permanent_qr(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)

    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="PERM-TRAY-0001", issued_date=None,
    )

    identifier = _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id)
    assert identifier is not None
    assert identifier.entity_type == "carrier"
    assert identifier.token


@pytest.mark.integration
def test_creating_an_asset_automatically_provisions_its_permanent_qr(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm

    asset = asset_service.register_asset(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        asset_type_code="germination_trolley", code="PERM-GT-0001", name="Trolley 1", commissioned_date=None,
    )

    identifier = _active_qr(db_session, tenant_id=tenant.id, column="asset_id", entity_id=asset.id)
    assert identifier is not None
    assert identifier.entity_type == "asset"


@pytest.mark.integration
def test_creating_a_location_automatically_provisions_its_permanent_qr(db_session, active_context_with_farm) -> None:
    tenant, user, _headers, farm = active_context_with_farm

    location = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="PERM-GH-01", name="Perm Greenhouse",
        parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
    )

    identifier = _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=location.id)
    assert identifier is not None
    assert identifier.entity_type == "location"


@pytest.mark.integration
def test_bulk_generated_locations_and_carriers_each_get_their_own_permanent_qr(
    db_session, active_context_with_farm
) -> None:
    tenant, user, _headers, farm = active_context_with_farm
    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    greenhouse = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="greenhouse", code="BULK-GH", name="Bulk GH",
        parent_location_id=None, greenhouse_classification="leafy_greens", occupiable=None,
    )
    # CLAUDE.md's own frozen Leafy chain: zone -> span -> grow table,
    # mandatory, no shortcuts.
    zone = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="zone", code="BULK-ZONE", name="Bulk Zone",
        parent_location_id=greenhouse.id, greenhouse_classification=None, occupiable=None,
    )
    span = location_service.create_location(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        location_type_code="span", code="BULK-SPAN", name="Bulk Span",
        parent_location_id=zone.id, greenhouse_classification=None, occupiable=None,
    )
    tables = location_service.bulk_generate_children(
        db_session, tenant_id=tenant.id, farm_id=farm.id, parent_id=span.id, actor_user_id=user.id,
        location_type_code="grow_table", code_prefix="BULK-GT-", start=1, end=3, pad_width=2,
        name_template=None, capacity=10,
    )
    carriers = carrier_service.bulk_register_carriers(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code_prefix="BULK-TR-", start=1, end=3, pad_width=2,
    )

    assert len(tables) == 3
    assert len(carriers) == 3
    for table in tables:
        assert _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=table.id) is not None
    for carrier in carriers:
        assert _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id) is not None


@pytest.mark.integration
def test_farm_setup_provisions_a_permanent_qr_for_every_location_and_asset_it_creates(
    db_session, active_context_with_farm
) -> None:
    from app.schemas.farm_setup import (
        GerminationChamberSetupConfig,
        GreenhouseSetupCreate,
        NurserySectionConfig,
        NurserySetupConfig,
        TrolleyLevelGeneratorConfig,
        TrolleySetupConfig,
    )

    tenant, user, _headers, farm = active_context_with_farm
    payload = GreenhouseSetupCreate(
        client_command_id=uuid.uuid4(),
        code="SETUP-GH",
        name="Setup Greenhouse",
        classification="nursery",
        nursery=NurserySetupConfig(
            seeding_station=NurserySectionConfig(code="SETUP-SS", name=None),
            germination_chamber=GerminationChamberSetupConfig(code="SETUP-GC", name=None, trolley_capacity=4),
            seedling_tables=None,
            intersalads_tables=None,
            intervines_tables=None,
            trolleys=[TrolleySetupConfig(code="SETUP-GT-01", name=None, levels=TrolleyLevelGeneratorConfig(
                level_count=2, level_prefix="L", level_pad_width=2, trays_per_level=5,
            ))],
            trolley_generator=None,
            seeding_machines=[],
        ),
        leafy=None,
        vines=None,
    )

    result = farm_setup_service.create_greenhouse_setup(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id, payload=payload,
    )

    greenhouse_qr = _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=result.greenhouse_id)
    assert greenhouse_qr is not None

    # Every Location/Asset this one composite command created has its own
    # permanent QR -- not just the top-level Greenhouse.
    locations = db_session.execute(
        select(location_service.Location).where(
            location_service.Location.tenant_id == tenant.id, location_service.Location.farm_id == farm.id,
        )
    ).scalars().all()
    assert len(locations) >= 3  # greenhouse, seeding_station, germination_chamber
    for loc in locations:
        assert _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=loc.id) is not None, (
            f"Location {loc.code} ({loc.id}) has no permanent QR"
        )

    assets = db_session.execute(
        select(asset_service.Asset).where(
            asset_service.Asset.tenant_id == tenant.id, asset_service.Asset.farm_id == farm.id,
        )
    ).scalars().all()
    assert len(assets) == 1  # the one trolley
    assert _active_qr(db_session, tenant_id=tenant.id, column="asset_id", entity_id=assets[0].id) is not None


@pytest.mark.integration
def test_retrying_qr_provisioning_for_an_already_provisioned_entity_never_creates_a_duplicate(
    db_session, active_context_with_farm
) -> None:
    """PILOT-SCAN-001D proof 4: idempotent retry. A Carrier already has its
    creation-time QR; calling the same idempotent provisioning entry
    point again (exactly what a later "Print Label" click, or a rerun of
    the backfill script, would do) must return the SAME token, never
    mint a second active identity."""
    tenant, user, _headers, farm = active_context_with_farm
    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)
    carrier = carrier_service.register_carrier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=user.id,
        specification_id=spec.id, code="RETRY-TRAY-0001", issued_date=None,
    )
    first = _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id)
    assert first is not None

    second = qr_service.generate_or_get_qr_identifier(
        db_session, tenant_id=tenant.id, farm_id=farm.id, entity_type="carrier", entity_id=carrier.id,
        actor_user_id=user.id,
    )
    assert second.id == first.id
    assert second.token == first.token

    all_active = db_session.execute(
        select(QrIdentifier).where(
            QrIdentifier.tenant_id == tenant.id, QrIdentifier.carrier_id == carrier.id,
            QrIdentifier.status == "active",
        )
    ).scalars().all()
    assert len(all_active) == 1


@pytest.mark.integration
def test_backfill_gives_every_pre_existing_entity_exactly_one_active_qr_and_is_safe_to_rerun(
    db_session, active_context_with_farm
) -> None:
    """PILOT-SCAN-001D proof 5: existing master data (simulated here via
    direct ORM inserts, bypassing the creation-time auto-provisioning hook
    entirely -- exactly what a Carrier/Location/Asset row created before
    this feature existed looks like; `qr_identifiers` rows can never be
    deleted once created -- CLAUDE.md rule 7/the table's own hard-delete-
    rejection trigger -- so a genuinely QR-less entity can only be built
    this way, never by creating-then-deleting a QR) gets exactly one
    active QR after one backfill run, and a second run changes nothing."""
    from app.models.asset import Asset
    from app.models.carrier import Carrier
    from app.models.location import Location
    from app.models.location_type import LocationType

    tenant, user, _headers, farm = active_context_with_farm
    spec = ensure_seed_tray_specification(db_session, tenant_id=tenant.id, actor_user_id=user.id)

    greenhouse_type_id = db_session.execute(
        select(LocationType.id).where(LocationType.code == "greenhouse")
    ).scalar_one()
    location = Location(
        tenant_id=tenant.id, farm_id=farm.id, location_type_id=greenhouse_type_id,
        code="PRE-GH", name="Pre-existing GH", parent_location_id=None,
        greenhouse_classification="leafy_greens",
    )
    db_session.add(location)

    carrier = Carrier(
        tenant_id=tenant.id, farm_id=farm.id, carrier_type_id=spec.carrier_type_id,
        specification_id=spec.id, code="PRE-TRAY-0001",
    )
    db_session.add(carrier)
    asset = Asset(
        tenant_id=tenant.id, farm_id=farm.id,
        asset_type_id=asset_service._get_asset_type_by_code(db_session, "germination_trolley").id,
        code="PRE-GT-0001", name="Pre-existing Trolley",
    )
    db_session.add(asset)
    db_session.commit()

    assert _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=location.id) is None
    assert _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id) is None
    assert _active_qr(db_session, tenant_id=tenant.id, column="asset_id", entity_id=asset.id) is None

    first_run = qr_service.backfill_missing_permanent_qr_identifiers(
        db_session, actor_user_id=user.id, tenant_id=tenant.id,
    )
    assert first_run["provisioned"]["location"] >= 1
    assert first_run["provisioned"]["carrier"] >= 1
    assert first_run["provisioned"]["asset"] >= 1
    assert first_run["errors"] == []

    loc_qr = _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=location.id)
    carrier_qr = _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id)
    asset_qr = _active_qr(db_session, tenant_id=tenant.id, column="asset_id", entity_id=asset.id)
    assert loc_qr is not None
    assert carrier_qr is not None
    assert asset_qr is not None

    # Rerun -- safe, idempotent, no duplicates, same tokens.
    second_run = qr_service.backfill_missing_permanent_qr_identifiers(
        db_session, actor_user_id=user.id, tenant_id=tenant.id,
    )
    assert second_run["provisioned"] == {"location": 0, "carrier": 0, "asset": 0}
    assert second_run["errors"] == []

    assert _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=location.id).token == loc_qr.token
    assert _active_qr(db_session, tenant_id=tenant.id, column="carrier_id", entity_id=carrier.id).token == carrier_qr.token
    assert _active_qr(db_session, tenant_id=tenant.id, column="asset_id", entity_id=asset.id).token == asset_qr.token

    for column, entity_id in (
        ("location_id", location.id), ("carrier_id", carrier.id), ("asset_id", asset.id),
    ):
        count = db_session.execute(
            select(QrIdentifier).where(
                QrIdentifier.tenant_id == tenant.id, getattr(QrIdentifier, column) == entity_id,
                QrIdentifier.status == "active",
            )
        ).scalars().all()
        assert len(count) == 1


@pytest.mark.integration
def test_backfill_dry_run_reports_counts_without_writing_anything(db_session, active_context_with_farm) -> None:
    from app.models.location import Location
    from app.models.location_type import LocationType

    tenant, user, _headers, farm = active_context_with_farm
    greenhouse_type_id = db_session.execute(
        select(LocationType.id).where(LocationType.code == "greenhouse")
    ).scalar_one()
    location = Location(
        tenant_id=tenant.id, farm_id=farm.id, location_type_id=greenhouse_type_id,
        code="DRY-GH", name="Dry-run GH", parent_location_id=None,
        greenhouse_classification="leafy_greens",
    )
    db_session.add(location)
    db_session.commit()

    result = qr_service.backfill_missing_permanent_qr_identifiers(
        db_session, actor_user_id=user.id, tenant_id=tenant.id, dry_run=True,
    )
    assert result["provisioned"]["location"] >= 1

    assert _active_qr(db_session, tenant_id=tenant.id, column="location_id", entity_id=location.id) is None
