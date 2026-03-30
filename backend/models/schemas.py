from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from backend.models.state import DetectedBug, FixPatch, InlineComment, LLMProvider, Mode, ReviewFinding


class IndexerOutput(BaseModel):
    rag_context_ids: list[str]


class ReviewerOutput(BaseModel):
    review_findings: list[ReviewFinding]
    confidence: float = Field(ge=0.0, le=1.0)


class BugHuntOutput(BaseModel):
    bugs_found: list[DetectedBug]


class IssueRaiserOutput(BaseModel):
    issues_raised: list[str]


class FixDrafterOutput(BaseModel):
    fix_patch: FixPatch
    approval_status: str


class ReviewRequest(BaseModel):
    pr_url: HttpUrl
    mode: Mode
    llm_provider: LLMProvider = "groq"
    llm_api_key: str | None = None
    llm_model: str | None = None


class SSEEvent(BaseModel):
    event: str = Field(min_length=1)
    data: dict[str, Any]
    thread_id: str = Field(min_length=1)


class ApproveRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    approved: bool


class HealthResponse(BaseModel):
    version: str
    status: str
    graph_ready: bool


class ReviewAcceptedResponse(BaseModel):
    thread_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)


class ApproveResponse(BaseModel):
    thread_id: str = Field(min_length=1)
    approval_status: str = Field(min_length=1)
    fix_patch: FixPatch
