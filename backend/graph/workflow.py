from langgraph.graph import END, START, StateGraph

from backend.agents.bug_hunter import hunt_bugs
from backend.agents.fix_drafter import draft_fix_patch
from backend.agents.indexer import fetch_pull_request_files
from backend.agents.issue_raiser import draft_issues
from backend.agents.reviewer import run_reviewer
from backend.models.state import WorkflowState


async def indexer_node(state: WorkflowState) -> dict:
    """Loads pull request file payloads into the retrieval store."""
    return await fetch_pull_request_files(state)


async def reviewer_node(state: WorkflowState) -> dict:
    """Executes the primary reviewer agent against stored chunks."""
    return await run_reviewer(state)


async def bug_hunter_node(state: WorkflowState) -> dict:
    """Runs deeper static reasoning to propose concrete defects."""
    return await hunt_bugs(state)


async def issue_raiser_node(state: WorkflowState) -> dict:
    """Formats candidate GitHub issues from confirmed findings."""
    return await draft_issues(state)


async def fix_drafter_node(state: WorkflowState) -> dict:
    """Synthesizes a patch proposal once approval logic allows it."""
    return await draft_fix_patch(state)


def route_after_reviewer(state: WorkflowState) -> str:
    """Decides whether analysis stops after review or continues onward."""
    if state["mode"] == "review_only":
        return END
    return "bug_hunter"


def route_after_issues(state: WorkflowState) -> str:
    """Chooses between automatic patching and an external approval gate."""
    if state["mode"] == "human_in_loop":
        return END
    return "fix_drafter"


def compile_workflow():
    """Returns an executable LangGraph compiled graph for the backend app."""
    graph = StateGraph(WorkflowState)
    graph.add_node("indexer", indexer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("bug_hunter", bug_hunter_node)
    graph.add_node("issue_raiser", issue_raiser_node)
    graph.add_node("fix_drafter", fix_drafter_node)
    graph.add_edge(START, "indexer")
    graph.add_edge("indexer", "reviewer")
    graph.add_conditional_edges(
        "reviewer",
        route_after_reviewer,
        path_map={END: END, "bug_hunter": "bug_hunter"},
    )
    graph.add_edge("bug_hunter", "issue_raiser")
    graph.add_conditional_edges(
        "issue_raiser",
        route_after_issues,
        path_map={END: END, "fix_drafter": "fix_drafter"},
    )
    graph.add_edge("fix_drafter", END)
    return graph.compile()
