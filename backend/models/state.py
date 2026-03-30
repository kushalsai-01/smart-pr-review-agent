from typing import Literal, TypedDict


Mode = Literal["review_only", "human_in_loop", "auto_pilot"]
LLMProvider = Literal["groq", "claude", "gemini"]


class InlineComment(TypedDict):
    file: str
    line: int
    body: str


class ReviewFinding(TypedDict):
    confidence: float
    review_summary: str
    inline_comments: list[InlineComment]


class DetectedBug(TypedDict):
    file: str
    line: int
    description: str
    severity: str
    suggested_fix: str


class FixPatch(TypedDict):
    diff: str
    files_changed: list[str]
    test_output: str
    co_authored_by: str


class WorkflowState(TypedDict):
    pr_url: str
    repo_full_name: str
    pr_number: int
    mode: Mode
    llm_provider: LLMProvider
    llm_model: str
    review_findings: list[ReviewFinding]
    bugs_found: list[DetectedBug]
    issues_raised: list[str]
    fix_patch: FixPatch
    approval_status: str
    rag_context_ids: list[str]
    thread_id: str
    error: str
