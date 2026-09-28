from datetime import datetime

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import InModel, OutModel, validate_http_url, validate_phone


class ContactCreate(InModel):
    company_id: int = Field(gt=0)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    seniority: str | None = Field(default=None, max_length=50)
    business_email: EmailStr | None = Field(default=None, max_length=320)
    business_phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)

    @field_validator("business_phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return validate_phone(v)

    @field_validator("linkedin_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        return validate_http_url(v)


class ContactOut(OutModel):
    id: int
    company_id: int
    first_name: str
    last_name: str | None
    full_name: str
    job_title: str | None
    department: str | None
    seniority: str | None
    business_email: str | None
    business_phone: str | None
    linkedin_url: str | None
    source: str
    source_reference: str | None
    data_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
