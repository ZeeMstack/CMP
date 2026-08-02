import pytest

from app.services import user_service
from app.services.errors import DuplicateUserIdentityError


@pytest.mark.integration
def test_create_user(db_session) -> None:
    user = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="sub-1",
        email="a@example.com",
        display_name="A",
    )
    assert user.id is not None
    assert user.status == "active"


@pytest.mark.integration
def test_oidc_issuer_and_subject_are_unique_together(db_session) -> None:
    user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="sub-1",
        email="a@example.com",
        display_name="A",
    )
    with pytest.raises(DuplicateUserIdentityError):
        user_service.create_user(
            db_session,
            oidc_issuer="https://issuer.example",
            oidc_subject="sub-1",
            email="different@example.com",
            display_name="B",
        )


@pytest.mark.integration
def test_email_is_not_globally_unique(db_session) -> None:
    user1 = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="sub-1",
        email="shared@example.com",
        display_name="A",
    )
    user2 = user_service.create_user(
        db_session,
        oidc_issuer="https://issuer.example",
        oidc_subject="sub-2",
        email="shared@example.com",
        display_name="B",
    )
    assert user1.id != user2.id
    assert user1.email == user2.email
