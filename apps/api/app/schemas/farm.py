import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator

_COUNTRY_CODE_RE = re.compile(r"^[A-Za-z]{2}$")


class FarmCreate(BaseModel):
    code: str
    name: str
    country_code: str
    city_region: str | None = None
    timezone: str

    @field_validator("code", "name")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, v: str) -> str:
        if not _COUNTRY_CODE_RE.match(v):
            raise ValueError("country_code must be exactly two letters")
        return v.upper()

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"invalid IANA timezone: {v}") from exc
        return v


class FarmRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    country_code: str
    city_region: str | None
    timezone: str
    status: str
