from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.errors import DuplicateUserIdentityError


def get_user_by_issuer_subject(db: Session, *, oidc_issuer: str, oidc_subject: str) -> User | None:
    """The only identity-resolution lookup CMP performs (AUTH-001A) --
    exact (oidc_issuer, oidc_subject) match, the same pair `users` already
    enforces uniqueness on. Never resolves by email."""
    return db.execute(
        select(User).where(User.oidc_issuer == oidc_issuer, User.oidc_subject == oidc_subject)
    ).scalar_one_or_none()


def find_users_by_email(db: Session, *, email: str) -> list[User]:
    """AUTHZ-OPS-001 (CTO correction pass): administrative-only lookup used
    by the "Add Existing User" flow to resolve a tenant admin's supplied
    email to an already-provisioned CMP User (one that has an existing
    `(oidc_issuer, oidc_subject)` identity -- see
    `docs/domain/AUTHORIZATION_MODEL.md`, "Identity binding"). Never used
    for authentication/identity resolution -- that remains exclusively
    `get_user_by_issuer_subject`.

    `users.email` carries no uniqueness constraint (only
    `(oidc_issuer, oidc_subject)` does), so this deliberately returns every
    match rather than silently picking one -- an earlier version of this
    function took "the first match in a stable order", which would have
    silently attached the WRONG identity to a tenant whenever two Users
    happen to share an email. The caller (`app.api.users.lookup_user_by_email`)
    is the one that decides what 0 / exactly 1 / more-than-1 results mean;
    this function never guesses on the caller's behalf."""
    return list(db.execute(select(User).where(User.email == email)).scalars().all())


def create_user(db: Session, *, oidc_issuer: str, oidc_subject: str, email: str, display_name: str) -> User:
    # Platform bootstrap action — no tenant exists yet at this point, so no
    # audit event is recorded here (per CMP-003 scope).
    user = User(
        oidc_issuer=oidc_issuer,
        oidc_subject=oidc_subject,
        email=email,
        display_name=display_name,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateUserIdentityError(f"{oidc_issuer}:{oidc_subject}") from exc
    db.refresh(user)
    return user
