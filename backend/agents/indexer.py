import hashlib
from typing import Any
import httpx

from backend.auth.github_auth import service_headers
from backend.config import Settings, get_settings
from backend.models.state import WorkflowState

_CHUNK_STORE: dict[str, str] = {}


def _chunk_payload(text: str, width: int) -> list[str]:
    """Splits a diff payload into fixed-width chunks for later retrieval."""
    cleaned = text.strip()
    if not cleaned:
        return []
    return [cleaned[i : i + width] for i in range(0, len(cleaned), width)]


async def fetch_pull_request_files(state: WorkflowState, settings: Settings | None = None) -> dict[str, Any]:
    """Downloads pull request file patches and records retrievable chunk identifiers."""
    resolved = settings or get_settings()
    owner, repository = state["repo_full_name"].split("/", 1)
    url = (
        f"https://api.github.com/repos/{owner}/{repository}/pulls/"
        f"{state['pr_number']}/files"
    )
    headers = service_headers(resolved)
    async with httpx.AsyncClient(timeout=45.0) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        files_payload = response.json()
    rag_ids: list[str] = []
    for index, item in enumerate(files_payload):
        filename = str(item.get("filename", f"file-{index}"))
        patch = str(item.get("patch", "") or item.get("blob_url", ""))
        for chunk_index, chunk in enumerate(_chunk_payload(patch, 1600)):
            digest = hashlib.sha256(
                f"{state['thread_id']}:{filename}:{chunk_index}:{chunk[:200]}".encode(
                    "utf-8",
                ),
            ).hexdigest()
            key = f"{digest[:16]}"
            _CHUNK_STORE[key] = chunk
            rag_ids.append(key)
    return {"rag_context_ids": rag_ids}


def fetch_chunks_for_ids(identifiers: list[str]) -> dict[str, str]:
    """Loads stored chunk text for each retriever identifier supplied."""
    return {key: _CHUNK_STORE[key] for key in identifiers if key in _CHUNK_STORE}
