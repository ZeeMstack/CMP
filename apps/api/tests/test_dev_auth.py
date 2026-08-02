import pytest

from app.core.dev_auth import check_dev_auth_startup_invariant
from app.core.settings import Settings
from app.main import create_app


def test_bootstrap_routes_not_registered_when_dev_auth_disabled() -> None:
    disabled_app = create_app(Settings(enable_dev_auth=False, env="development"))
    paths = disabled_app.openapi()["paths"].keys()
    assert "/dev/bootstrap/tenants" not in paths
    assert "/dev/bootstrap/users" not in paths
    assert "/dev/bootstrap/memberships" not in paths


def test_bootstrap_routes_registered_when_dev_auth_enabled() -> None:
    enabled_app = create_app(Settings(enable_dev_auth=True, env="development"))
    paths = enabled_app.openapi()["paths"].keys()
    assert "/dev/bootstrap/tenants" in paths
    assert "/dev/bootstrap/users" in paths
    assert "/dev/bootstrap/memberships" in paths


def test_startup_rejected_when_dev_auth_enabled_outside_development() -> None:
    with pytest.raises(RuntimeError):
        check_dev_auth_startup_invariant(Settings(enable_dev_auth=True, env="production"))


def test_startup_allowed_when_dev_auth_disabled_in_any_env() -> None:
    check_dev_auth_startup_invariant(Settings(enable_dev_auth=False, env="production"))


@pytest.mark.integration
def test_dev_header_auth_rejected_when_dev_auth_disabled(client, monkeypatch) -> None:
    import app.core.dev_auth as dev_auth_module

    monkeypatch.setattr(dev_auth_module.settings, "enable_dev_auth", False)
    response = client.get(
        "/farms",
        headers={
            "X-Dev-Tenant-Id": "00000000-0000-0000-0000-000000000000",
            "X-Dev-User-Id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 401
