from typing import Literal, TypedDict


Mode = Literal["review_only", "human_in_loop", "auto_pilot"]


class WorkflowState(TypedDict):
    pr_url: str
    repo_full_name: str
    pr_number: int
    mode: Mode
    review_findings: list[str]
    bugs_found: list[str]
    issues_raised: list[str]
    fix_patch: str
    approval_status: str
    rag_context_ids: list[str]
    thread_id: str
