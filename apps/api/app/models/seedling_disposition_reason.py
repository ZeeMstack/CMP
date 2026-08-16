from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SeedlingDispositionReason(Base):
    """NURSERY-OPS-003B: global, platform-defined catalog of the approved
    Seedling-stage biological disposition reasons -- no `tenant_id`, no
    application mutation API, seeded once by migration (matches the
    `location_types`/`carrier_types`/`asset_types` convention). `code` is
    the primary key (a deliberate, evidence-based departure from those
    tables' own UUID-PK-plus-separate-code-column shape): `code` is
    referenced directly as a natural-key FK from
    `seedling_disposition_events.reason_code`, which is what lets the
    'OTHER requires a note' rule be a same-row CHECK constraint on the
    event table itself (`reason_code <> 'OTHER' OR note ...`) rather than
    needing a cross-table trigger -- see migration
    `<this ticket's revision>` for the exact constraint.

    Deliberately excludes NON_GERMINATION (a pre-handoff Germination fact,
    already excluded from `SeedlingEntry.starting_living_seedling_count` by
    construction) and TRANSPLANT_DAMAGE (belongs exclusively to a future
    transplant transformation's own reconciliation, via
    `TransplantSourceLine.discarded_plant_count`)."""

    __tablename__ = "seedling_disposition_reasons"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
