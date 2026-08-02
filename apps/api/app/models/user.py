import uuid

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.common import TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    oidc_issuer: Mapped[str] = mapped_column(String, nullable=False)
    oidc_subject: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")

    __table_args__ = (
        UniqueConstraint("oidc_issuer", "oidc_subject", name="ux_users_issuer_subject"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
    )
