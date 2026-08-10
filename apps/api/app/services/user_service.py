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
