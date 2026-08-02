from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.services.errors import DuplicateUserIdentityError


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
