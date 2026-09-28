import re
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

T = TypeVar("T")

_PHONE_RE = re.compile(r"^[0-9+()\-.\s/x]{4,50}$", re.IGNORECASE)


class OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class InModel(BaseModel):
    """Base for request bodies: rejects unknown fields, trims strings, maps "" to null."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _blank_strings_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: (None if isinstance(v, str) and not v.strip() else v) for k, v in data.items()}
        return data


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class UserBrief(OutModel):
    id: int
    name: str


class EntityRef(OutModel):
    id: int
    name: str


def validate_phone(value: str | None) -> str | None:
    if value is not None and not _PHONE_RE.match(value):
        raise ValueError("Phone number may contain digits, spaces and + ( ) - . / only")
    return value


def validate_http_url(value: str | None) -> str | None:
    if value is not None and not re.match(r"^https?://[^\s]+\.[^\s]+$", value, re.IGNORECASE):
        raise ValueError("Must be a full http(s) URL")
    return value


def require_value(value: Any, field: str) -> Any:
    if value is None:
        raise ValueError(f"{field} cannot be empty")
    return value
