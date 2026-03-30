from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from backend.agents.indexer import fetch_chunks_for_ids
from backend.config import get_settings
from backend.models.state import WorkflowState


async def run_reviewer(state: WorkflowState) -> dict[str, list[str]]:
    """Generates structured review findings grounded in indexed diff chunks."""
    context = fetch_chunks_for_ids(state["rag_context_ids"])
    if not context:
        return {"review_findings": ["No retrievable diff chunks were available for review."]}
    blocks = [f"{name}:\n{text}" for name, text in context.items()]
    prompt = "\n\n".join(blocks)[:12000]
    settings = get_settings()
    llm = ChatOpenAI(
        api_key=settings.openai_api_key,
        model="gpt-4.1-mini",
        temperature=0.2,
    )
    messages = [
        SystemMessage(
            content=(
                "You are a senior code reviewer. Respond with one finding per line, "
                "prefixed with '- ', and keep each line under 240 characters."
            ),
        ),
        HumanMessage(
            content=(
                f"Repository {state['repo_full_name']} PR #{state['pr_number']}.\n"
                f"{prompt}"
            ),
        ),
    ]
    result = await llm.ainvoke(messages)
    text = str(result.content)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    findings = [line[2:].strip() if line.startswith("- ") else line for line in lines]
    if not findings:
        findings = [text.strip()]
    return {"review_findings": findings}
