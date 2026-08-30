"""PILOT-SETUP-001B8: product Setup Checklist / Readiness -- a read-only
view over actual persisted Tenant/Farm state, entirely distinct from
`pilot_bootstrap_service.run_readiness_check` (which evaluates a YAML
`PilotConfig` for the admin bootstrap CLI, never a real API/UI concern).

Status semantics are deliberately narrow -- see
`app.services.farm_setup_readiness_service` module docstring for the
milestone-by-milestone algorithm this schema is shaped around.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

ReadinessItemStatus = Literal["pass", "missing", "warning", "not_applicable"]
MilestoneStatus = Literal["ready", "incomplete"]
MilestoneCode = Literal["sowing", "production", "post_harvest", "full_pilot"]


class FarmSetupReadinessItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    label: str
    status: ReadinessItemStatus
    detail: str = ""


class FarmSetupReadinessMilestone(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: MilestoneCode
    label: str
    status: MilestoneStatus
    items: list[FarmSetupReadinessItem]


class FarmSetupReadinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    farm_id: str
    overall: MilestoneStatus
    milestones: list[FarmSetupReadinessMilestone]
