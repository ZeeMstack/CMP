import pytest

from app.services import tenant_service
from app.services.errors import DuplicateTenantCodeError


@pytest.mark.integration
def test_create_tenant(db_session) -> None:
    tenant = tenant_service.create_tenant(db_session, code="acme", name="Acme Farms")
    assert tenant.id is not None
    assert tenant.code == "acme"
    assert tenant.status == "active"


@pytest.mark.integration
def test_tenant_code_unique_case_insensitively(db_session) -> None:
    tenant_service.create_tenant(db_session, code="acme", name="Acme Farms")
    with pytest.raises(DuplicateTenantCodeError):
        tenant_service.create_tenant(db_session, code="ACME", name="Duplicate")
