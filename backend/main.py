import asyncio
import json
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from backend.agents.fix_drafter import draft_fix_patch
from backend.auth.github_auth import assert_app_credentials_match, validate_oauth_token
from backend.config import get_settings
from backend.graph.workflow import compile_workflow
from backend.models.schemas import (
    ApproveRequest,
    ApproveResponse,
    HealthResponse,
    ReviewAcceptedResponse,
    ReviewRequest,
)
from backend.models.state import WorkflowState

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RUNS: dict[str, dict[str, Any]] = {}


def _build_initial(payload: ReviewRequest) -> WorkflowState:
    """Builds the LangGraph workflow input from the incoming review request."""
    return {
        "pr_url": str(payload.pr_url),
        "repo_full_name": payload.repo_full_name,
        "pr_number": payload.pr_number,
        "mode": payload.mode,
        "review_findings": [],
        "bugs_found": [],
        "issues_raised": [],
        "fix_patch": "",
        "approval_status": "queued",
        "rag_context_ids": [],
        "thread_id": payload.thread_id,
    }


async def _ensure_github_header(authorization: str | None) -> None:
    """Verifies GitHub credentials when a bearer token header is provided."""
    if authorization is None:
        return
    lowered = authorization.lower()
    if not lowered.startswith("bearer "):
        raise HTTPException(status_code=401, detail="invalid_authorization_scheme")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="empty_bearer_token")
    await validate_oauth_token(token)


async def _execute_workflow(payload: ReviewRequest) -> None:
    """Streams LangGraph updates into the per-thread queue until completion."""
    thread_id = payload.thread_id
    run = _RUNS.get(thread_id)
    if not run:
        return
    queue: asyncio.Queue = run["queue"]
    graph = compile_workflow()
    initial = _build_initial(payload)
    try:
        get_settings()
        await queue.put({"event": "phase", "data": {"phase": "started"}})
        final: WorkflowState | None = None
        async for snapshot in graph.astream(initial, stream_mode="values"):
            if isinstance(snapshot, dict):
                final = snapshot
                run["state"] = snapshot
            await queue.put({"event": "state", "data": snapshot})
        if final is None:
            final = await graph.ainvoke(initial)
            run["state"] = final
        await queue.put({"event": "phase", "data": {"phase": "finished"}})
    except Exception as exc:
        await queue.put({"event": "error", "data": {"message": str(exc)}})
        raise
    finally:
        run["running"] = False
        await queue.put(None)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Reports readiness for orchestration traffic."""
    return HealthResponse(status="ok")


@app.post("/review", response_model=ReviewAcceptedResponse)
async def review(
    payload: ReviewRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> ReviewAcceptedResponse:
    """Accepts a pull request review request and schedules background analysis."""
    await _ensure_github_header(authorization)
    assert_app_credentials_match(get_settings())
    if payload.thread_id in _RUNS and _RUNS[payload.thread_id].get("running"):
        raise HTTPException(status_code=409, detail="thread_busy")
    queue: asyncio.Queue = asyncio.Queue()
    _RUNS[payload.thread_id] = {
        "queue": queue,
        "state": None,
        "running": True,
    }
    background_tasks.add_task(_execute_workflow, payload)
    return ReviewAcceptedResponse(thread_id=payload.thread_id, phase="scheduled")


@app.get("/stream/{thread_id}")
async def stream(
    thread_id: str,
    authorization: str | None = Header(default=None),
) -> EventSourceResponse:
    """Streams server-sent events describing workflow progress for a thread."""
    await _ensure_github_header(authorization)

    async def emitter():
        """Yields encoded server-sent events sourced from the workflow queue."""
        run = _RUNS.get(thread_id)
        if not run:
            yield {
                "event": "error",
                "data": json.dumps({"message": "unknown_thread"}),
            }
            return
        queue: asyncio.Queue = run["queue"]
        while True:
            item = await queue.get()
            if item is None:
                yield {"event": "complete", "data": json.dumps({"done": True})}
                break
            yield {
                "event": item["event"],
                "data": json.dumps(item["data"], default=str),
            }

    return EventSourceResponse(emitter())


@app.post("/approve", response_model=ApproveResponse)
async def approve(
    payload: ApproveRequest,
    authorization: str | None = Header(default=None),
) -> ApproveResponse:
    """Records human approval decisions and finalizes fix drafting when allowed."""
    await _ensure_github_header(authorization)
    run = _RUNS.get(payload.thread_id)
    if not run:
        raise HTTPException(status_code=404, detail="unknown_thread")
    state = run.get("state")
    if not isinstance(state, dict):
        raise HTTPException(status_code=409, detail="state_not_ready")
    if not payload.approved:
        merged = dict(state)
        merged["approval_status"] = "rejected"
        run["state"] = merged
        return ApproveResponse(
            thread_id=payload.thread_id,
            approval_status=merged["approval_status"],
            fix_patch=str(merged.get("fix_patch", "")),
        )
    patch_update = await draft_fix_patch(state)
    merged = dict(state)
    merged.update(patch_update)
    run["state"] = merged
    return ApproveResponse(
        thread_id=payload.thread_id,
        approval_status=str(merged.get("approval_status", "")),
        fix_patch=str(merged.get("fix_patch", "")),
    )
