import json

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from backend.models.schemas import BugHuntOutput
from backend.models.state import WorkflowState
from backend.rag.code_indexer import search_codebase
from backend.llm_security import BLOCKED_PREFIX, is_blocked_response, secure_llm_call


@traceable(run_type="llm", name="hunt_bugs_llm")
async def _hunt_bugs_llm(system: SystemMessage, human: HumanMessage) -> str:
    """Calls the configured LLM to generate bug reports."""
    prompt_text = f"{system.content}\n\n{human.content}"
    return await secure_llm_call(prompt_text)


@traceable(run_type="agent", name="hunt_bugs")
async def hunt_bugs(state: WorkflowState) -> WorkflowState:
    """Finds concrete bugs using review findings and code retrieval."""
    repo_name = state["repo_full_name"]
    review_findings = state.get("review_findings", [])
    suspicious_queries: list[str] = []
    for finding in review_findings:
        review_summary = str(finding.get("review_summary", ""))
        if review_summary:
            suspicious_queries.append(review_summary)
        for comment in finding.get("inline_comments", []):
            body = str(comment.get("body", ""))
            if body:
                suspicious_queries.append(body)

    rag_blocks: list[str] = []
    for query in suspicious_queries[:5]:
        try:
            docs = search_codebase(query[:2500], repo_name, k=5)
            rag_blocks.append(
                "\n".join(
                    [
                        f"{doc.metadata.get('file','')}:{doc.metadata.get('start_line',0)}-{doc.metadata.get('end_line',0)}\n{doc.page_content[:2000]}"
                        for doc in docs
                    ],
                )[:6000],
            )
        except Exception as exc:
            rag_blocks.append(f"RAG search failed: {exc}"[:6000])

    rag_context = "\n\n".join(rag_blocks)[:12000]
    system = SystemMessage(
        content=(
            "You are a senior bug hunter. "
            "Return only JSON matching the BugHuntOutput schema. "
            "Each bug must include file, line, description, severity, and suggested_fix."
        ),
    )
    human = HumanMessage(
        content=json.dumps(
            {
                "repo_full_name": repo_name,
                "pr_number": state["pr_number"],
                "review_findings": review_findings,
                "rag_context": rag_context,
            },
            ensure_ascii=False,
        ),
    )
    updated = dict(state)
    try:
        raw = await _hunt_bugs_llm(system, human)
        if is_blocked_response(raw) or raw.startswith(BLOCKED_PREFIX):
            updated["bugs_found"] = []
            updated["error"] = "LLM call blocked by input security policy."
        else:
            parsed = BugHuntOutput.model_validate_json(raw)
            updated["bugs_found"] = parsed.bugs_found
            updated["error"] = ""
    except Exception as exc:
        updated["bugs_found"] = []
        updated["error"] = str(exc)[:2000]
    return updated
