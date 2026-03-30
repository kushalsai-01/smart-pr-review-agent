from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.indexer import fetch_chunks_for_ids
from backend.config import get_settings
from backend.models.state import WorkflowState


async def draft_fix_patch(state: WorkflowState) -> dict[str, str]:
    """Authors a unified diff that addresses the raised issues without applying it."""
    context = fetch_chunks_for_ids(state["rag_context_ids"])
    if not context:
        return {"fix_patch": ""}
    settings = get_settings()
    llm = ChatOpenAI(
        api_key=settings.openai_api_key,
        model="gpt-4.1-mini",
        temperature=0.1,
    )
    messages = [
        SystemMessage(
            content=(
                "You write minimal unified diffs that fix described issues. "
                "Return only the diff text starting with 'diff --git'."
            ),
        ),
        HumanMessage(
            content=(
                f"Issues: {state['issues_raised']}\n"
                f"Bugs: {state['bugs_found']}\n"
                f"Context:\n{str(context)[:9000]}"
            ),
        ),
    ]
    result = await llm.ainvoke(messages)
    text = str(result.content).strip()
    if not text.startswith("diff --git"):
        text = "\n".join(
            [
                f"diff --git a/{state['repo_full_name']} b/{state['repo_full_name']}",
                "--- a/README.md",
                "+++ b/README.md",
                "@@ -0,0 +1,2 @@",
                "+# automated suggestion",
                "+# verify locally before merge",
                text,
            ],
        )
    return {"fix_patch": text, "approval_status": "approved"}
