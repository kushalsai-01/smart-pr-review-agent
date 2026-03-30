from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.config import get_settings
from backend.models.state import WorkflowState


async def draft_issues(state: WorkflowState) -> dict[str, object]:
    """Turns detected defects into GitHub-ready issue descriptions."""
    settings = get_settings()
    llm = ChatOpenAI(
        api_key=settings.openai_api_key,
        model="gpt-4.1-mini",
        temperature=0.25,
    )
    messages = [
        SystemMessage(
            content=(
                "Draft actionable GitHub issues. Each issue must be one line formatted as "
                "TITLE | BODY where BODY summarizes impacted files and a mitigation."
            ),
        ),
        HumanMessage(
            content=(
                f"Repo {state['repo_full_name']} PR #{state['pr_number']}.\n"
                f"Bugs: {state['bugs_found']}\n"
                f"Review notes: {state['review_findings']}"
            ),
        ),
    ]
    result = await llm.ainvoke(messages)
    text = str(result.content)
    issues = [line.strip() for line in text.splitlines() if "|" in line]
    extra: dict[str, object] = {"issues_raised": issues or [text.strip()]}
    if state["mode"] == "human_in_loop":
        extra["approval_status"] = "pending"
    else:
        extra["approval_status"] = "skipped"
    return extra
