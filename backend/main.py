import asyncio
import re
import uuid
from typing import Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from backend.auth.github_auth import verify_webhook_signature
from backend.llm_security import clear_llm_context, set_llm_context, secure_llm_call
from backend.config import settings
from backend.graph.workflow import get_compiled_graph
from langgraph.errors import GraphInterrupt
from backend.models.schemas import (
    ApproveRequest,
    ApproveResponse,
    HealthResponse,
    ReviewAcceptedResponse,
    ReviewRequest,
    SSEEvent,
)
from backend.models.state import FixPatch, LLMProvider, WorkflowState


class SecureTestRequest(BaseModel):
    """Request body for secure LLM test endpoint."""

    prompt: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes persistence and workflow readiness."""
    import os

    os.makedirs(settings.chroma_persist_dir, exist_ok=True)
    try:
        _ = get_compiled_graph()
        app.state.graph_ready = True
    except Exception:
        app.state.graph_ready = False
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RUNS: dict[str, dict[str, Any]] = {}


_PR_URL_RE = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)")


def _parse_pr_url(pr_url: str) -> tuple[str, str, int]:
    """Extracts owner, repo, and PR number from a GitHub PR URL."""
    match = _PR_URL_RE.match(pr_url)
    if not match:
        raise ValueError("invalid_pr_url")
    owner = match.group("owner")
    repo = match.group("repo")
    number = int(match.group("number"))
    return owner, repo, number


def _initial_fix_patch() -> FixPatch:
    """Creates an initial empty fix patch result structure."""
    return {"diff": "", "files_changed": [], "test_output": "", "co_authored_by": ""}


def _build_initial_state(payload: ReviewRequest, thread_id: str) -> WorkflowState:
    """Builds the initial workflow state from the review request."""
    owner, repo, number = _parse_pr_url(str(payload.pr_url))

    def _default_llm_model(provider: LLMProvider) -> str:
        """Provides built-in default models per provider."""
        if provider == "groq":
            return "llama-3.3-70b"
        if provider == "claude":
            return "claude-3-5-sonnet-latest"
        return "gemini-1.5-pro-latest"

    llm_provider: LLMProvider = payload.llm_provider
    llm_model = payload.llm_model or _default_llm_model(llm_provider)

    return {
        "pr_url": str(payload.pr_url),
        "repo_full_name": f"{owner}/{repo}",
        "pr_number": number,
        "mode": payload.mode,
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "review_findings": [],
        "bugs_found": [],
        "issues_raised": [],
        "fix_patch": _initial_fix_patch(),
        "approval_status": "queued",
        "rag_context_ids": [],
        "thread_id": thread_id,
        "error": "",
    }


def _step_events(state: WorkflowState) -> dict[str, bool]:
    """Determines which workflow steps have produced results."""
    indexing_done = len(state.get("rag_context_ids", [])) > 0
    reviewing_done = len(state.get("review_findings", [])) > 0
    bug_hunting_done = len(state.get("bugs_found", [])) > 0
    issue_raising_done = len(state.get("issues_raised", [])) > 0
    fix_diff = state.get("fix_patch", {}).get("diff", "")
    fixing_done = bool(str(fix_diff).strip())
    return {
        "indexing": indexing_done,
        "reviewing": reviewing_done,
        "bug_hunting": bug_hunting_done,
        "issue_raising": issue_raising_done,
        "fixing": fixing_done,
    }


def _data_for_event(event_name: str, state: WorkflowState, error_message: str | None = None) -> dict[str, Any]:
    """Builds the SSE data payload for a given workflow event."""
    if event_name == "indexing":
        return {"rag_context_ids": state.get("rag_context_ids", [])}
    if event_name == "reviewing":
        return {"review_findings": state.get("review_findings", [])}
    if event_name == "bug_hunting":
        return {"bugs_found": state.get("bugs_found", [])}
    if event_name == "issue_raising":
        return {"issues_raised": state.get("issues_raised", [])}
    if event_name == "fixing":
        return {"fix_patch": state.get("fix_patch", {})}
    if event_name == "awaiting_approval":
        return {"approval_status": state.get("approval_status", "queued")}
    if event_name == "complete":
        return {
            "approval_status": state.get("approval_status", ""),
            "fix_patch": state.get("fix_patch", {}),
        }
    if event_name == "error":
        return {"message": error_message or ""}
    return {"state": state}


def _emit_event(thread_id: str, event_name: str, data: dict[str, Any]) -> SSEEvent:
    """Builds an SSEEvent payload."""
    sse = SSEEvent(event=event_name, data=data, thread_id=thread_id)
    return sse


async def _run_graph(thread_id: str) -> None:
    """Runs the workflow from the latest checkpoint until completion or interrupt."""
    run = _RUNS.get(thread_id)
    if not run:
        return
    queue: asyncio.Queue = run["queue"]
    state: WorkflowState = run["state"]
    reported: set[str] = run["reported"]
    try:
        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": thread_id}}
        async for snapshot in graph.astream(state, config=config, stream_mode="values"):
            state = snapshot if isinstance(snapshot, dict) else state
            run["state"] = state
            flags = _step_events(state)
            for step, done in flags.items():
                if done and step not in reported:
                    reported.add(step)
                    await queue.put(
                        {
                            "event": step,
                            "data": _emit_event(thread_id, step, _data_for_event(step, state)).model_dump_json(),
                        }
                    )
        await queue.put(
            {
                "event": "complete",
                "data": _emit_event(thread_id, "complete", _data_for_event("complete", state)).model_dump_json(),
            }
        )
        await queue.put(None)
    except GraphInterrupt:
        await queue.put(
            {
                "event": "awaiting_approval",
                "data": _emit_event(
                    thread_id,
                    "awaiting_approval",
                    _data_for_event("awaiting_approval", state),
                ).model_dump_json(),
            }
        )
    except Exception as exc:
        await queue.put(
            {
                "event": "error",
                "data": _emit_event(
                    thread_id,
                    "error",
                    _data_for_event("error", state, error_message=str(exc)),
                ).model_dump_json(),
            }
        )
        await queue.put(None)
    finally:
        clear_llm_context()


async def _resume_graph(thread_id: str) -> None:
    """Resumes workflow execution after human approval interrupt."""
    run = _RUNS.get(thread_id)
    if not run:
        return
    queue: asyncio.Queue = run["queue"]
    state: WorkflowState = run["state"]
    reported: set[str] = run["reported"]
    set_llm_context(
        provider=state["llm_provider"],
        api_key=run.get("llm_api_key"),
        model=state.get("llm_model"),
    )
    try:
        graph = get_compiled_graph()
        config = {"configurable": {"thread_id": thread_id}}
        await graph.aupdate_state(
            config,
            {
                "approval_status": state.get("approval_status", "queued"),
            },
        )
        async for snapshot in graph.astream({}, config=config, stream_mode="values"):
            state = snapshot if isinstance(snapshot, dict) else state
            run["state"] = state
            flags = _step_events(state)
            for step, done in flags.items():
                if done and step not in reported:
                    reported.add(step)
                    await queue.put(
                        {
                            "event": step,
                            "data": _emit_event(thread_id, step, _data_for_event(step, state)).model_dump_json(),
                        }
                    )
        await queue.put(
            {
                "event": "complete",
                "data": _emit_event(thread_id, "complete", _data_for_event("complete", state)).model_dump_json(),
            }
        )
        await queue.put(None)
    except Exception as exc:
        await queue.put(
            {
                "event": "error",
                "data": _emit_event(
                    thread_id,
                    "error",
                    _data_for_event("error", state, error_message=str(exc)),
                ).model_dump_json(),
            }
        )
        await queue.put(None)
    finally:
        clear_llm_context()


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Reports readiness and graph availability."""
    return HealthResponse(
        version="0.1.0",
        status="ok",
        graph_ready=bool(getattr(app.state, "graph_ready", False)),
    )


@app.post("/review", response_model=ReviewAcceptedResponse)
async def review(payload: ReviewRequest) -> ReviewAcceptedResponse:
    """Accepts a review request and starts background workflow execution."""
    if not app.state.graph_ready:
        return ReviewAcceptedResponse(thread_id="unavailable", phase="graph_not_ready")
    thread_id = str(uuid.uuid4())
    state = _build_initial_state(payload, thread_id)
    queue: asyncio.Queue = asyncio.Queue()
    _RUNS[thread_id] = {
        "queue": queue,
        "state": state,
        "reported": set(),
        "llm_api_key": payload.llm_api_key,
    }
    set_llm_context(provider=state["llm_provider"], api_key=payload.llm_api_key, model=state.get("llm_model"))
    asyncio.create_task(_run_graph(thread_id))
    clear_llm_context()
    return ReviewAcceptedResponse(thread_id=thread_id, phase="scheduled")


@app.get("/stream/{thread_id}")
async def stream(thread_id: str) -> EventSourceResponse:
    """Streams server-sent events for a thread id."""
    run = _RUNS.get(thread_id)
    if not run:
        async def _unknown():
            yield {
                "event": "error",
                "data": _emit_event(thread_id, "error", {"message": "unknown_thread"}).model_dump_json(),
            }

        return EventSourceResponse(_unknown())
    queue: asyncio.Queue = run["queue"]

    async def emitter():
        """Consumes the queue and yields SSE events."""
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return EventSourceResponse(emitter())


@app.post("/approve", response_model=ApproveResponse)
async def approve(payload: ApproveRequest) -> ApproveResponse:
    """Updates approval status and resumes the workflow when interrupted."""
    run = _RUNS.get(payload.thread_id)
    if not run:
        raise ValueError("unknown_thread")
    state: WorkflowState = run["state"]
    updated = dict(state)
    updated["approval_status"] = "approved" if payload.approved else "rejected"
    run["state"] = updated
    asyncio.create_task(_resume_graph(payload.thread_id))
    return ApproveResponse(
        thread_id=payload.thread_id,
        approval_status=updated["approval_status"],
        fix_patch=updated["fix_patch"],
    )


@app.post("/llm/secure-test")
async def secure_test(payload: SecureTestRequest) -> dict[str, str]:
    """Secures a prompt then calls the LLM using the security wrapper."""
    response = await secure_llm_call(payload.prompt)
    return {"response": response}


async def _handle_review_from_pr_payload(pr_url: str, mode: str) -> str:
    """Creates a thread and triggers review for a PR payload."""
    thread_id = str(uuid.uuid4())
    state = _build_initial_state(ReviewRequest(pr_url=pr_url, mode=mode), thread_id)
    queue: asyncio.Queue = asyncio.Queue()
    _RUNS[thread_id] = {
        "queue": queue,
        "state": state,
        "reported": set(),
        "llm_api_key": None,
    }
    set_llm_context(provider=state["llm_provider"], api_key=None, model=state.get("llm_model"))
    asyncio.create_task(_run_graph(thread_id))
    clear_llm_context()
    return thread_id


@app.post("/webhook")
async def webhook(request: Request) -> dict[str, Any]:
    """Receives GitHub webhook events and triggers reviews for PR changes."""
    body = await request.body()
    signature = str(request.headers.get("X-Hub-Signature-256", ""))
    if not verify_webhook_signature(body, signature):
        return {"status": "invalid_signature"}
    event_type = str(request.headers.get("X-GitHub-Event", ""))
    payload = await request.json()
    if event_type != "pull_request":
        return {"status": "ignored"}
    action = str(payload.get("action", ""))
    if action not in {"opened", "synchronize"}:
        return {"status": "ignored"}
    pr = payload.get("pull_request") or {}
    pr_url = str(pr.get("html_url", ""))
    repo_full_name = pr.get("base", {}).get("repo", {}).get("full_name") or payload.get("repository", {}).get("full_name")
    if not pr_url and repo_full_name:
        pr_url = str(payload.get("pull_request", {}).get("html_url", ""))
    if not pr_url:
        return {"status": "missing_pr_url"}
    mode = "auto_pilot"
    thread_id = await _handle_review_from_pr_payload(pr_url, mode)
    return {"status": "triggered", "thread_id": thread_id}
