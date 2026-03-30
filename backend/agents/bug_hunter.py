from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.indexer import fetch_chunks_for_ids
from backend.config import get_settings
from backend.models.state import WorkflowState


async def hunt_bugs(state: WorkflowState) -> dict[str, list[str]]:
    """Surfaces likely defect patterns and failure modes from the pull request diff."""
    context = fetch_chunks_for_ids(state["rag_context_ids"])
    if not context:
        return {"bugs_found": ["Insufficient diff context prevented deeper bug analysis."]}
    payload = "\n\n".join(context.values())[:12000]
    settings = get_settings()
    llm = ChatOpenAI(
        api_key=settings.openai_api_key,
        model="gpt-4.1-mini",
        temperature=0.1,
    )
    messages = [
        SystemMessage(
            content=(
                "You hunt concrete bugs: races, null handling, bad assumptions, security. "
                "Emit bullet lines starting with '* ' and keep them factual."
            ),
        ),
        HumanMessage(
            content=(
                f"Review prior findings: {state['review_findings']}\n\nDIFF:\n{payload}"
            ),
        ),
    ]
    result = await llm.ainvoke(messages)
    text = str(result.content)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bugs = [line[2:].strip() if line.startswith("* ") else line for line in lines]
    if not bugs:
        bugs = [text.strip()]
    return {"bugs_found": bugs}
