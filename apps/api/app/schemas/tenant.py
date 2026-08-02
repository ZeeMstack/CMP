import uuid

from pydantic import BaseModel, ConfigDict, field_validator


class TenantCreate(BaseModel):
    code: str
    name: str

    @field_validator("code", "name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    status: str
