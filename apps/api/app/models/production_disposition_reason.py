from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProductionDispositionReason(Base):
    """LEAFY-OPS-001: global, platform-defined catalog of the approved
    Production Biological Disposition reasons -- no `tenant_id`, no
    application mutation API, seeded once by migration (mirrors
    `SeedlingDispositionReason`'s own pattern exactly, deliberately NOT the
    same table: this ticket's reason vocabulary is written for the
    Production Cultivation Plate stage, not the Seed Tray stage, and the two
    should not silently share a taxonomy). `code` is the primary key, a
    natural-key FK from `production_disposition_events.reason_code`, which
    is what lets the 'other requires a note' rule be a same-row CHECK
    constraint on the event table itself."""

    __tablename__ = "production_disposition_reasons"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
