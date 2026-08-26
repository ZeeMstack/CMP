"""POSTHARVEST-OPS-001D direct-SQL DB-integrity tests for
`recall_scope_graded_produce_lots` and the widened `recall_cases` typed
source shape -- mirrors `test_recall_direct_sql.py`'s own established
proof style for the three original CMP-020 scope tables."""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from tests._recall_graded_lot_scenario import (
    build_committed_tenant_farm,
    cleanup_recall_graded_lot_scenario,
    committed_connection,
    now,
    open_case,
)
from tests.test_recall_graded_lot_case_opening import _build_graded_pair
from app.services import farm_service


@pytest.mark.integration
def test_direct_sql_cross_tenant_graded_scope_insert_rejected(test_engine) -> None:
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

        with committed_connection(test_engine) as session2:
            other_tenant, other_user, other_farm = build_committed_tenant_farm(session2)
            other_tenant_id = other_tenant.id
            session2.commit()
            other_farm_id = other_farm.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_scope_graded_produce_lots "
                            "(id, tenant_id, farm_id, recall_case_id, graded_produce_lot_id) "
                            "VALUES (:id, :tid, :fid, :cid, :gid)"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": other_tenant_id, "fid": other_farm_id, "cid": case_id,
                            "gid": gpl_a_id,
                        },
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, other_tenant_id)


@pytest.mark.integration
def test_direct_sql_cross_farm_graded_scope_insert_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

            other_farm = farm_service.create_farm(
                session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-other-{uuid.uuid4().hex[:8]}",
                name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
            )
            session.commit()
            other_farm_id = other_farm.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_scope_graded_produce_lots "
                            "(id, tenant_id, farm_id, recall_case_id, graded_produce_lot_id) "
                            "VALUES (:id, :tid, :fid, :cid, :gid)"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": tenant_id, "fid": other_farm_id, "cid": case_id,
                            "gid": gpl_a_id,
                        },
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_duplicate_graded_scope_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_scope_graded_produce_lots "
                            "(id, tenant_id, farm_id, recall_case_id, graded_produce_lot_id) "
                            "VALUES (:id, :tid, :fid, :cid, :gid)"
                        ),
                        {"id": uuid.uuid4(), "tid": tenant_id, "fid": farm_id, "cid": case_id, "gid": gpl_a_id},
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_graded_scope_update_and_delete_rejected(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            case = open_case(session, tenant, farm, user, graded_produce_lot_id=gpl_a_id)
            session.commit()
            case_id = case.id

        with test_engine.connect() as conn:
            scope_row_id = conn.execute(
                text("SELECT id FROM recall_scope_graded_produce_lots WHERE recall_case_id = :cid"),
                {"cid": case_id},
            ).scalar_one()

        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(
                        text("UPDATE recall_scope_graded_produce_lots SET recorded_time = now() WHERE id = :id"),
                        {"id": scope_row_id},
                    )
        with test_engine.connect() as conn:
            with pytest.raises(ProgrammingError):
                with conn.begin():
                    conn.execute(
                        text("DELETE FROM recall_scope_graded_produce_lots WHERE id = :id"), {"id": scope_row_id}
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_graded_lot_source_case_without_scope_row_cannot_commit(test_engine) -> None:
    """The deferred structural-reconciliation trigger: a `recall_cases` row
    with `graded_produce_lot_id` populated but no matching
    `recall_scope_graded_produce_lots` row must fail once its deferred
    constraint is checked, never silently commit. `SET CONSTRAINTS ALL
    IMMEDIATE` inside a `begin_nested()` savepoint forces the check without
    ever committing the outer transaction -- mirrors
    `test_grading_db_integrity.py`'s own established technique for this
    exact class of proof."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)

            with pytest.raises(DBAPIError, match="no matching recall_scope_graded_produce_lots row"):
                with session.begin_nested():
                    session.execute(
                        text(
                            "INSERT INTO recall_cases "
                            "(id, tenant_id, farm_id, code, graded_produce_lot_id, reason_code, reason_text, "
                            "effective_time, actor_user_id, client_command_id, request_fingerprint) "
                            "VALUES (:id, :tid, :fid, :code, :gid, 'CONTAMINATION', 'no scope row', :eff, :uid, "
                            ":ccid, 'fp-no-scope')"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": tenant.id, "fid": farm.id,
                            "code": f"RC-NOSCOPE-{uuid.uuid4().hex[:8]}", "gid": gpl_a_id, "eff": now(),
                            "uid": user.id, "ccid": uuid.uuid4(),
                        },
                    )
                    session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_typed_source_check_rejects_zero_and_multiple_sources_involving_graded_lot(test_engine) -> None:
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            farm_id = farm.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            tenant_id_v, farm_id_v, user_id_v = tenant.id, farm.id, user.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_cases "
                            "(id, tenant_id, farm_id, code, reason_code, reason_text, effective_time, "
                            "actor_user_id, client_command_id, request_fingerprint) "
                            "VALUES (:id, :tid, :fid, :code, 'CONTAMINATION', 'zero sources', :eff, :uid, :ccid, 'fp-zero')"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": tenant_id_v, "fid": farm_id_v,
                            "code": f"RC-ZERO-{uuid.uuid4().hex[:8]}", "eff": now(), "uid": user_id_v,
                            "ccid": uuid.uuid4(),
                        },
                    )

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_cases "
                            "(id, tenant_id, farm_id, code, graded_produce_lot_id, finished_goods_lot_id, "
                            "reason_code, reason_text, effective_time, actor_user_id, client_command_id, "
                            "request_fingerprint) "
                            "VALUES (:id, :tid, :fid, :code, :gid, :fgid, 'CONTAMINATION', 'two sources', :eff, "
                            ":uid, :ccid, 'fp-two')"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": tenant_id_v, "fid": farm_id_v,
                            "code": f"RC-TWO-{uuid.uuid4().hex[:8]}", "gid": gpl_a_id,
                            "fgid": uuid.uuid4(), "eff": now(), "uid": user_id_v, "ccid": uuid.uuid4(),
                        },
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_cross_farm_recall_case_typed_source_rejected(test_engine) -> None:
    """The composite `fk_recall_cases_tenant_farm_graded_lot` FK also
    rejects a `recall_cases` row whose `graded_produce_lot_id` belongs to
    a DIFFERENT farm within the SAME tenant -- a distinct integrity
    boundary from `test_direct_sql_cross_farm_graded_scope_insert_rejected`
    above (which tests the scope table, not the typed source on
    `recall_cases` itself)."""
    tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)
            tenant_id_v, user_id_v = tenant.id, user.id

            other_farm = farm_service.create_farm(
                session, tenant_id=tenant.id, actor_user_id=user.id, code=f"farm-other-{uuid.uuid4().hex[:8]}",
                name="Other Farm", country_code="AE", city_region=None, timezone="Asia/Dubai",
            )
            session.commit()
            other_farm_id = other_farm.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_cases "
                            "(id, tenant_id, farm_id, code, graded_produce_lot_id, reason_code, reason_text, "
                            "effective_time, actor_user_id, client_command_id, request_fingerprint) "
                            "VALUES (:id, :tid, :fid, :code, :gid, 'CONTAMINATION', 'cross farm fk', :eff, :uid, "
                            ":ccid, 'fp-cross-farm-fk')"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": tenant_id_v, "fid": other_farm_id,
                            "code": f"RC-XFARMFK-{uuid.uuid4().hex[:8]}", "gid": gpl_a_id, "eff": now(),
                            "uid": user_id_v, "ccid": uuid.uuid4(),
                        },
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)


@pytest.mark.integration
def test_direct_sql_cross_tenant_recall_case_typed_source_rejected(test_engine) -> None:
    """The composite `fk_recall_cases_tenant_farm_graded_lot` FK rejects a
    `recall_cases` row whose `graded_produce_lot_id` belongs to a different
    tenant/farm than the case's own -- the same integrity boundary the
    other three typed-source composite FKs already enforce."""
    tenant_id = None
    other_tenant_id = None
    try:
        with committed_connection(test_engine) as session:
            tenant, user, farm = build_committed_tenant_farm(session)
            tenant_id = tenant.id
            _, _, _, gpl_a_id, _ = _build_graded_pair(session, tenant, user, farm)

        with committed_connection(test_engine) as session2:
            other_tenant, other_user, other_farm = build_committed_tenant_farm(session2)
            other_tenant_id = other_tenant.id
            session2.commit()
            other_tenant_id_v, other_farm_id_v, other_user_id_v = other_tenant.id, other_farm.id, other_user.id

        with test_engine.connect() as conn:
            with pytest.raises(IntegrityError):
                with conn.begin():
                    conn.execute(
                        text(
                            "INSERT INTO recall_cases "
                            "(id, tenant_id, farm_id, code, graded_produce_lot_id, reason_code, reason_text, "
                            "effective_time, actor_user_id, client_command_id, request_fingerprint) "
                            "VALUES (:id, :tid, :fid, :code, :gid, 'CONTAMINATION', 'cross tenant fk', :eff, :uid, "
                            ":ccid, 'fp-cross-tenant-fk')"
                        ),
                        {
                            "id": uuid.uuid4(), "tid": other_tenant_id_v, "fid": other_farm_id_v,
                            "code": f"RC-XFK-{uuid.uuid4().hex[:8]}", "gid": gpl_a_id, "eff": now(),
                            "uid": other_user_id_v, "ccid": uuid.uuid4(),
                        },
                    )
    finally:
        if tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, tenant_id)
        if other_tenant_id is not None:
            cleanup_recall_graded_lot_scenario(test_engine, other_tenant_id)
