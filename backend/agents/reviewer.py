import json
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable

from backend.auth.github_auth import generate_jwt, get_installation_token
from backend.models.schemas import ReviewRequest, ReviewerOutput
from backend.models.state import WorkflowState
from backend.rag.code_indexer import search_codebase
from backend.llm_security import BLOCKED_PREFIX, is_blocked_response, secure_llm_call


@traceable(run_type="agent", name="review_pr")
async def review_pr(state: WorkflowState) -> WorkflowState:
    """Reviews a pull request and populates structured review findings."""
    owner, repo = state["repo_full_name"].split("/", 1)
    jwt_token = generate_jwt()
    installation_url = f"https://api.github.com/repos/{owner}/{repo}/installation"
    headers_jwt = {
        "Authorization": f"Bearer {jwt_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        installation_resp = await client.get(installation_url, headers=headers_jwt)
        installation_resp.raise_for_status()
        installation_payload = installation_resp.json()
        installation_id = int(installation_payload["id"])
        installation_token = await get_installation_token(installation_id)
        pr_files_url = (
            f"https://api.github.com/repos/{owner}/{repo}/pulls/{state['pr_number']}/files"
            "?per_page=100"
        )
        pr_files_headers = {
            "Authorization": f"Bearer {installation_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        files_resp = await client.get(pr_files_url, headers=pr_files_headers)
        files_resp.raise_for_status()
        pr_files_payload = files_resp.json()

    diff_chunks: list[str] = []
    rag_chunks: list[str] = []
    for file_item in pr_files_payload:
        filename = str(file_item.get("filename", ""))
        patch = file_item.get("patch")
        if not filename or not patch:
            continue
        patch_text = str(patch)
        excerpt = patch_text[:6000]
        diff_chunks.append(f"{filename}\n{excerpt}")
        try:
            docs = search_codebase(f"{filename}\n{excerpt[:2000]}", state["repo_full_name"], k=5)
            rag_chunks.append(
                "\n".join(
                    [
                        f"{doc.metadata.get('file','')}:{doc.metadata.get('start_line',0)}-{doc.metadata.get('end_line',0)}\n{doc.page_content[:2000]}"
                        for doc in docs
                    ],
                )[:6000]
            )
        except Exception as exc:
            rag_chunks.append(f"RAG search failed for {filename}: {exc}"[:6000])

    diff_context = "\n\n".join(diff_chunks)[:12000]
    rag_context = "\n\n".join(rag_chunks)[:12000]
    system = SystemMessage(
        content=(
            "You are a senior software engineer performing a PR review. "
            "Return only JSON matching the ReviewerOutput schema. "
            "Set ReviewerOutput.confidence between 0 and 1. "
            "Populate review_findings with exactly one element containing review_summary, inline_comments, and confidence. "
            "inline_comments is an array (possibly empty) of objects with file, line, and body."
        ),
    )
    review_request = ReviewRequest(pr_url=state["pr_url"], mode=state["mode"])
    human = HumanMessage(
        content=json.dumps(
            {
                "repo_full_name": state["repo_full_name"],
                "pr_number": state["pr_number"],
                "mode": state["mode"],
                "pr_url": str(review_request.pr_url),
                "diff_context": diff_context,
                "rag_context": rag_context,
            },
            ensure_ascii=False,
        ),
    )

    @traceable(run_type="llm", name="review_pr_llm")
    async def _review_pr_llm() -> str:
        """Calls the configured LLM to generate a structured PR review."""
        prompt_text = f"{system.content}\n\n{human.content}"
        return await secure_llm_call(prompt_text)

    try:
        raw = await _review_pr_llm()
        if is_blocked_response(raw) or raw.startswith(BLOCKED_PREFIX):
            findings = [
                {
                    "confidence": 0.0,
                    "review_summary": "LLM call blocked by input security policy.",
                    "inline_comments": [],
                }
            ]
        else:
            parsed = ReviewerOutput.model_validate_json(raw)
            findings = []
            for item in parsed.review_findings:
                entry: dict[str, Any] = dict(item)
                entry.setdefault("inline_comments", [])
                entry["confidence"] = float(parsed.confidence)
                findings.append(entry)
            if not findings:
                findings = [
                    {
                        "confidence": float(parsed.confidence),
                        "review_summary": "",
                        "inline_comments": [],
                    }
                ]
    except Exception as exc:
        findings = [
            {
                "confidence": 0.0,
                "review_summary": str(exc)[:2000],
                "inline_comments": [],
            }
        ]

    pr_comment_body = ""
    if findings and findings[0].get("review_summary"):
        pr_comment_body = findings[0]["review_summary"]
    if not pr_comment_body:
        pr_comment_body = "Review findings generated by smart-pr-review-agent."

    async with httpx.AsyncClient(timeout=30.0) as client:
        reviews_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{state['pr_number']}/reviews"
        reviews_headers = {
            "Authorization": f"Bearer {installation_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        reviews_payload = {"event": "COMMENT", "body": pr_comment_body}
        await client.post(reviews_url, headers=reviews_headers, json=reviews_payload)

    updated = dict(state)
    updated["review_findings"] = findings
    updated["error"] = ""
    return updated
