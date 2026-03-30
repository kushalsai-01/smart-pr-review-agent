from pydantic import BaseModel, Field, HttpUrl

from backend.models.state import Mode


class HealthResponse(BaseModel):
    status: str = Field(min_length=1)


class ReviewRequest(BaseModel):
    pr_url: HttpUrl
    repo_full_name: str = Field(min_length=1)
    pr_number: int = Field(ge=1)
    mode: Mode
    thread_id: str = Field(min_length=1)


class ReviewAcceptedResponse(BaseModel):
    thread_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)


class ApproveRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    approved: bool


class ApproveResponse(BaseModel):
    thread_id: str = Field(min_length=1)
    approval_status: str = Field(min_length=1)
    fix_patch: str
