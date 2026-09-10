"""AUTHZ-OPS-001: human-readable names/descriptions for the approved
tenant-membership role codes, for the Users & Roles administration screen's
role picker (ticket section 5/17).

Descriptive/presentation data only -- this module has no bearing on
authorization. The one and only authorization source remains
`app.core.permissions.ROLE_PERMISSIONS`; nothing here is ever consulted by
`require_permission`/`has_permission`, and a description changing here can
never change what a role may actually do.

Every `app.models.membership.APPROVED_ROLE_CODES` value has exactly one
entry here (enforced by `tests/test_role_catalog.py`), so the role picker
can never silently drift out of sync with the codes the database itself
accepts.
"""

from __future__ import annotations

ROLE_CATALOG: tuple[dict[str, str], ...] = (
    {
        "code": "tenant_admin",
        "name": "Tenant Admin",
        "description": "Tenant configuration and user administration. Full access to every module.",
    },
    {
        "code": "farm_manager",
        "name": "Farm Manager",
        "description": "Site infrastructure setup, full visibility across the farm, and senior recall escalation.",
    },
    {
        "code": "head_grower",
        "name": "Head Grower",
        "description": "Planning, nursery, production, and agronomy operations.",
    },
    {
        "code": "production_supervisor",
        "name": "Production Supervisor",
        "description": "Day-to-day supervision of floor execution across production stages.",
    },
    {
        "code": "operator",
        "name": "Operator",
        "description": "Routine farm operations: sowing, transplanting, movement, and harvest recording.",
    },
    {
        "code": "storekeeper",
        "name": "Storekeeper",
        "description": "Receiving and custody of incoming seed lots.",
    },
    {
        "code": "qc_officer",
        "name": "Quality Officer",
        "description": "Quality inspection and disposition operations.",
    },
    {
        "code": "packing_supervisor",
        "name": "Packing Supervisor",
        "description": "Packing execution and finished-goods handoff.",
    },
    {
        "code": "cold_store_supervisor",
        "name": "Cold Store Supervisor",
        "description": "Finished-goods cold storage custody and movement.",
    },
    {
        "code": "dispatch_officer",
        "name": "Dispatch Officer",
        "description": "Dispatch execution -- goods leaving the farm.",
    },
    {
        "code": "auditor",
        "name": "Auditor",
        "description": "Broad read-only visibility for compliance and traceability review.",
    },
    {
        "code": "read_only",
        "name": "Read Only",
        "description": "Broad read-only visibility across operations, with no ability to make changes.",
    },
)
