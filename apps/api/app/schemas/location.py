from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

GREENHOUSE_CLASSIFICATIONS = frozenset({"nursery", "leafy_greens", "vines", "mixed", "other"})

MAX_BULK_CHILDREN = 500


def _normalize_code(v: str) -> str:
    v = v.strip().upper()
    if not v:
        raise ValueError("code must not be blank")
    return v


def _normalize_classification(v: str | None) -> str | None:
    if v is None:
        return v
    v = v.strip().lower()
    if v not in GREENHOUSE_CLASSIFICATIONS:
        allowed = ", ".join(sorted(GREENHOUSE_CLASSIFICATIONS))
        raise ValueError(f"greenhouse_classification must be one of: {allowed}")
    return v


class LocationCreate(BaseModel):
    location_type_code: str
    code: str
    name: str
    parent_location_id: uuid.UUID | None = None
    greenhouse_classification: str | None = None
    occupiable: bool | None = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        return _normalize_code(v)

    @field_validator("greenhouse_classification")
    @classmethod
    def validate_classification(cls, v: str | None) -> str | None:
        return _normalize_classification(v)

    @model_validator(mode="after")
    def classification_matches_type(self) -> "LocationCreate":
        is_greenhouse = self.location_type_code == "greenhouse"
        if is_greenhouse and self.greenhouse_classification is None:
            raise ValueError("greenhouse locations require greenhouse_classification")
        if not is_greenhouse and self.greenhouse_classification is not None:
            raise ValueError("only greenhouse locations may have greenhouse_classification")
        return self


class LocationBulkChildrenCreate(BaseModel):
    location_type_code: str
    code_prefix: str
    start: int
    end: int
    pad_width: int
    name_template: str | None = None

    @field_validator("code_prefix")
    @classmethod
    def validate_prefix(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("code_prefix must not be blank")
        return v

    @model_validator(mode="after")
    def validate_range(self) -> "LocationBulkChildrenCreate":
        if self.start < 1:
            raise ValueError("start must be a positive integer")
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        if self.pad_width < 1:
            raise ValueError("pad_width must be a positive integer")
        count = self.end - self.start + 1
        if count > MAX_BULK_CHILDREN:
            raise ValueError(f"cannot generate more than {MAX_BULK_CHILDREN} children per command")
        return self


class LocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    farm_id: uuid.UUID
    parent_location_id: uuid.UUID | None
    location_type_id: uuid.UUID
    code: str
    name: str
    status: str
    greenhouse_classification: str | None
    occupiable: bool


class LocationPathEntry(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class LocationPathRead(BaseModel):
    location_id: uuid.UUID
    path: list[LocationPathEntry]
    path_string: str


class LocationTreeNode(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    location_type_id: uuid.UUID
    status: str
    occupiable: bool
    children: list["LocationTreeNode"] = []


LocationTreeNode.model_rebuild()
