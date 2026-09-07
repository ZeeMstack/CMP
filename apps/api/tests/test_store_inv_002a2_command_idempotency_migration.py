"""STORE-INV-002A.2 CTO closure pass: migration downgrade-guard proof for
`abcdb6f371f9_inventory_quality_command_idempotency.py` -- mirrors
`test_store_inv_002a1_migration.py`'s own pattern exactly, one revision
step higher. `f1a4c8e7b2d5` itself is never touched by this migration or
this test file.

Also proves the migration's own `enforce_inventory_quality_command_
insert_integrity` trigger directly, via raw SQL `INSERT` statements into
`inventory_quality_commands` that bypass `inventory_quality_service`
entirely -- these are DB-integrity tests, not service tests: the point is
that even a hand-crafted SQL statement (or a hypothetical future service
bug) cannot slip a stale/wrong-cohort/automatic target past the DB
layer."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import scripts.reset_test_database
from app.core.settings import settings
from app.services import goods_receipt_service, inventory_quality_service
from app.services.goods_receipt_service import GoodsReceiptLineInput
from tests._store_inv_scenario import build_category, build_item, uom_id
from tests._traceability_scenario import build_committed_tenant_farm

API_ROOT = Path(__file__).resolve().parent.parent


def _cfg() -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings.test_database_url)
    return cfg


@pytest.mark.integration
def test_downgrade_clean_when_empty(test_engine, alembic_head_restore) -> None:
    """Resets cmp_test to a genuinely empty-then-head state itself (same
    hermetic pattern as test_store_inv_002a1_migration.py), so this test
    never depends on execution order relative to any other test that
    commits real command/event rows via a separate connection."""
    scripts.reset_test_database.main()
    command.downgrade(_cfg(), "-1")
    with test_engine.connect() as conn:
        tables = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'inventory_quality_commands'"
            )
        ).scalar_one()
        has_column = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'quality_disposition_events' AND column_name = 'command_id'"
            )
        ).scalar_one()
    assert tables == 0
    assert has_column == 0
    command.upgrade(_cfg(), "head")


def _receive_qc_cohort(session, *, tenant, farm, actor_user_id):
    category = build_category(session, tenant, actor_user_id=actor_user_id)
    item = build_item(
        session, tenant, category.id, uom_id(session, "kg"), actor_user_id=actor_user_id,
        lot_tracking_required=True, qc_release_required=True,
    )
    receipt = goods_receipt_service.record_goods_receipt(
        session, tenant_id=tenant.id, farm_id=farm.id, actor_user_id=actor_user_id, client_command_id=uuid.uuid4(),
        received_at=datetime.now(timezone.utc), supplier_name=None, external_system=None, external_document_id=None,
        notes=None,
        lines=[
            GoodsReceiptLineInput(
                inventory_item_id=item.id, entered_quantity=Decimal("50"), entered_uom_id=uom_id(session, "kg"),
                manufacturer_name="Acme", manufacturer_lot_reference=f"LOT-{uuid.uuid4().hex[:8]}",
            )
        ],
    )
    from sqlalchemy import select

    from app.models.goods_receipt_line import GoodsReceiptLine
    from app.models.inventory_quantity_cohort import InventoryQuantityCohort

    line = session.execute(
        select(GoodsReceiptLine).where(GoodsReceiptLine.goods_receipt_id == receipt.id)
    ).scalar_one()
    cohort = session.execute(
        select(InventoryQuantityCohort).where(InventoryQuantityCohort.source_goods_receipt_line_id == line.id)
    ).scalar_one()
    return cohort.id


@pytest.mark.integration
def test_downgrade_blocked_once_inventory_quality_command_exists(test_engine, alembic_head_restore) -> None:
    conn = test_engine.connect()
    session = Session(bind=conn)
    try:
        tenant, user, farm = build_committed_tenant_farm(session)
        cohort_id = _receive_qc_cohort(session, tenant=tenant, farm=farm, actor_user_id=user.id)
        from app.services import user_service

        other = user_service.create_user(
            session, oidc_issuer="https://issuer.example", oidc_subject=f"mig-{uuid.uuid4().hex[:8]}",
            email=f"mig-{uuid.uuid4().hex[:8]}@example.com", display_name="Migration Test User",
        )
        inventory_quality_service.record_quality_disposition(
            session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
            cohort_id=cohort_id, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
        )
    finally:
        session.close()
        conn.close()

    with pytest.raises(RuntimeError, match="inventory quality command idempotency"):
        command.downgrade(_cfg(), "-1")


# --- Direct-SQL bypass proofs for enforce_inventory_quality_command_insert_integrity ---


def _quarantine_event_id(session, *, cohort_id) -> uuid.UUID:
    from sqlalchemy import select

    from app.models.quality_disposition_event import QualityDispositionEvent

    return session.execute(
        select(QualityDispositionEvent.id).where(
            QualityDispositionEvent.inventory_quantity_cohort_id == cohort_id,
            QualityDispositionEvent.event_kind == "RECEIVED_QUARANTINED",
        )
    ).scalar_one()


def _raw_insert_command(
    session, *, tenant_id: uuid.UUID, cohort_id: uuid.UUID, operation_kind: str, target_event_id, actor_user_id: uuid.UUID,
) -> None:
    """Bypasses `inventory_quality_service` entirely -- a hand-crafted SQL
    INSERT, exactly as a direct-SQL attacker or a hypothetical future
    service bug would issue it. Proves the DB trigger itself, not the
    service-layer check that normally runs first."""
    session.execute(
        text(
            "INSERT INTO inventory_quality_commands "
            "(id, tenant_id, inventory_quantity_cohort_id, operation_kind, target_event_id, actor_user_id, "
            "client_command_id, request_fingerprint) "
            "VALUES (:id, :tenant_id, :cohort_id, :operation_kind, :target_event_id, :actor_user_id, "
            ":client_command_id, :fingerprint)"
        ),
        {
            "id": uuid.uuid4(), "tenant_id": tenant_id, "cohort_id": cohort_id, "operation_kind": operation_kind,
            "target_event_id": target_event_id, "actor_user_id": actor_user_id, "client_command_id": uuid.uuid4(),
            "fingerprint": "direct-sql-bypass-test",
        },
    )
    session.flush()


@pytest.mark.integration
def test_direct_sql_partial_correct_targeting_stale_event_rejected(db_session, active_context_with_farm) -> None:
    """(A) A direct SQL INSERT naming a HUMAN event that has since been
    superseded by a later decision on the same cohort is rejected by the
    trigger itself -- never merely by the service layer."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    from app.services import user_service

    other = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"stale-{uuid.uuid4().hex[:8]}",
        email=f"stale-{uuid.uuid4().hex[:8]}@example.com", display_name="Stale Test User",
    )
    released = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
    )
    # A later decision supersedes it -- `released` is now stale.
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    with pytest.raises(DBAPIError, match="not the current disposition event"):
        _raw_insert_command(
            db_session, tenant_id=tenant.id, cohort_id=cohort_id, operation_kind="PARTIAL_CORRECT",
            target_event_id=released.id, actor_user_id=user.id,
        )


@pytest.mark.integration
def test_direct_sql_partial_correct_targeting_other_cohort_rejected(db_session, active_context_with_farm) -> None:
    """(B) A direct SQL INSERT naming a real, current human event that
    belongs to a DIFFERENT cohort than the command's own is rejected."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_a = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    cohort_b = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    from app.services import user_service

    other = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"xcohort-{uuid.uuid4().hex[:8]}",
        email=f"xcohort-{uuid.uuid4().hex[:8]}@example.com", display_name="Cross Cohort Test User",
    )
    event_on_a = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_a, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
    )

    with pytest.raises(DBAPIError, match="does not belong to this command's own inventory_quantity_cohort_id"):
        _raw_insert_command(
            db_session, tenant_id=tenant.id, cohort_id=cohort_b, operation_kind="PARTIAL_CORRECT",
            target_event_id=event_on_a.id, actor_user_id=user.id,
        )


@pytest.mark.integration
def test_direct_sql_partial_correct_targeting_opening_quarantine_rejected(db_session, active_context_with_farm) -> None:
    """(C) The automatic, receipt-time RECEIVED_QUARANTINED fact is never
    a valid target for PARTIAL_CORRECT (nor CORRECT) -- rejected at the
    DB layer directly, independent of the service layer."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    quarantine_event_id = _quarantine_event_id(db_session, cohort_id=cohort_id)

    with pytest.raises(DBAPIError, match="never the automatic opening fact"):
        _raw_insert_command(
            db_session, tenant_id=tenant.id, cohort_id=cohort_id, operation_kind="PARTIAL_CORRECT",
            target_event_id=quarantine_event_id, actor_user_id=user.id,
        )


@pytest.mark.integration
def test_direct_sql_partial_correct_targeting_actual_current_event_accepted(db_session, active_context_with_farm) -> None:
    """(D) A direct SQL INSERT naming the cohort's actual, genuinely
    current human decision is accepted by the trigger (the row inserts
    cleanly) -- proving the trigger validates real cases correctly, not
    merely rejects everything."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    from app.services import user_service

    other = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"valid-{uuid.uuid4().hex[:8]}",
        email=f"valid-{uuid.uuid4().hex[:8]}@example.com", display_name="Valid Target Test User",
    )
    current = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
    )

    _raw_insert_command(
        db_session, tenant_id=tenant.id, cohort_id=cohort_id, operation_kind="PARTIAL_CORRECT",
        target_event_id=current.id, actor_user_id=user.id,
    )
    # No exception raised -- the row inserted cleanly.


@pytest.mark.integration
def test_direct_sql_correct_stale_target_rejected_independently(db_session, active_context_with_farm) -> None:
    """(E) The same stale-target rejection holds for whole-cohort CORRECT
    too, proven directly at the DB layer independent of `.1`'s own
    REVERSAL-target-currency trigger (which only fires once an actual
    REVERSAL row is inserted) -- this new trigger rejects the malformed
    COMMAND header itself, before any event row would even be attempted."""
    tenant, user, _headers, farm = active_context_with_farm
    cohort_id = _receive_qc_cohort(db_session, tenant=tenant, farm=farm, actor_user_id=user.id)
    from app.services import user_service

    other = user_service.create_user(
        db_session, oidc_issuer="https://issuer.example", oidc_subject=f"correct-stale-{uuid.uuid4().hex[:8]}",
        email=f"correct-stale-{uuid.uuid4().hex[:8]}@example.com", display_name="Correct Stale Test User",
    )
    released = inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=other.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="RELEASED", effective_time=datetime.now(timezone.utc),
    )
    inventory_quality_service.record_quality_disposition(
        db_session, tenant_id=tenant.id, actor_user_id=user.id, client_command_id=uuid.uuid4(),
        cohort_id=cohort_id, disposition="HELD", effective_time=datetime.now(timezone.utc) + timedelta(minutes=1),
    )

    with pytest.raises(DBAPIError, match="not the current disposition event"):
        _raw_insert_command(
            db_session, tenant_id=tenant.id, cohort_id=cohort_id, operation_kind="CORRECT",
            target_event_id=released.id, actor_user_id=user.id,
        )
