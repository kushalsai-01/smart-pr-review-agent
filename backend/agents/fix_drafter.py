import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from pydantic import BaseModel

from backend.auth.github_auth import generate_jwt, get_installation_token
from backend.models.state import WorkflowState
from backend.rag.code_indexer import clone_repository, search_codebase
from backend.llm_security import BLOCKED_PREFIX, is_blocked_response, secure_llm_call


class _FilePatch(BaseModel):
    path: str
    content: str


class _FixPlan(BaseModel):
    files: list[_FilePatch]


def _repo_has_py_tests(repo_dir: Path) -> bool:
    """Detects whether the repository likely uses pytest."""
    return (repo_dir / "pyproject.toml").exists() or (repo_dir / "pytest.ini").exists() or (repo_dir / "tests").exists()


def _repo_has_js_tests(repo_dir: Path) -> bool:
    """Detects whether the repository likely uses npm tests."""
    return (repo_dir / "package.json").exists()


def _test_command(repo_dir: Path) -> list[str]:
    """Selects the test command based on detected project type."""
    if _repo_has_py_tests(repo_dir):
        return ["pytest", "-q"]
    if _repo_has_js_tests(repo_dir):
        return ["npm", "test"]
    return ["python", "-m", "compileall", "."]


def _safe_repo_relative_path(repo_dir: Path, file_path: str) -> Path:
    """Resolves a repo-relative path safely within the repository."""
    cleaned = file_path.replace("\\", "/").lstrip("/")
    if cleaned.startswith("../") or "/../" in cleaned or ".." in cleaned.split("/"):
        raise ValueError("invalid_file_path")
    resolved = (repo_dir / cleaned).resolve()
    if repo_dir.resolve() not in resolved.parents and resolved != repo_dir.resolve():
        raise ValueError("path_escape")
    return resolved


def _run_tests(repo_dir: Path) -> tuple[bool, str]:
    """Runs tests and returns pass status and combined output."""
    cmd = _test_command(repo_dir)
    proc = subprocess.run(
        cmd,
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    ok = proc.returncode == 0
    combined = ""
    if proc.stdout:
        combined += proc.stdout
    if proc.stderr:
        combined += proc.stderr
    return ok, combined[-20000:]


def _git_diff(repo_dir: Path) -> str:
    """Returns the current git diff for the working tree."""
    proc = subprocess.run(
        ["git", "diff"],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    return (proc.stdout or "").strip()


def _restore_worktree(repo_dir: Path) -> None:
    """Restores repository files to HEAD."""
    subprocess.run(
        ["git", "checkout", "--", "."],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
        check=False,
    )


@traceable(run_type="llm", name="draft_fix_llm")
async def _draft_fix_llm(prompt_body: str) -> str:
    """Calls the configured LLM to draft a fix plan."""
    system = SystemMessage(
        content=(
            "You are an expert software engineer. "
            "Return only JSON matching the _FixPlan schema: "
            "files is a list of {path, content} objects. "
            "Use repository-relative paths. "
            "Provide complete new file contents."
        ),
    )
    human = HumanMessage(content=prompt_body)
    prompt_text = f"{system.content}\n\n{human.content}"
    return await secure_llm_call(prompt_text)


def _extract_fix_plan_json(raw: str) -> str:
    """Extracts the JSON object from an LLM response."""
    match = re.search(r"\{[\\s\\S]*\}", raw.strip())
    return match.group(0) if match else raw.strip()


async def _fetch_installation_token(repo_full_name: str) -> str:
    """Fetches a GitHub installation access token for repository cloning."""
    owner, repo = repo_full_name.split("/", 1)
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
    return installation_token


async def draft_fix(state: WorkflowState) -> WorkflowState:
    """Generates, applies, tests, and returns a fix patch for the identified bugs."""
    repo_full_name = state["repo_full_name"]
    installation_token = await _fetch_installation_token(repo_full_name)
    owner, repo = repo_full_name.split("/", 1)
    repo_url = f"https://github.com/{owner}/{repo}.git"
    clone_dir = await asyncio.to_thread(clone_repository, repo_url, installation_token)
    temp_root = Path(clone_dir).parent
    attempt_outputs: list[str] = []
    files_changed: list[str] = []
    fix_diff = ""
    test_output = ""
    co_authored_by = "Co-authored-by: smart-pr-review-bot <smart-pr-review-bot@users.noreply.github.com>"
    blocked_error = ""
    try:
        for attempt in range(3):
            if attempt > 0:
                _restore_worktree(Path(clone_dir))
            rag_blocks: list[str] = []
            for bug in state.get("bugs_found", []):
                bug_file = str(bug.get("file", ""))
                bug_line = int(bug.get("line", 0))
                bug_desc = str(bug.get("description", ""))
                query = f"{bug_file}:{bug_line}\n{bug_desc}\nSuggested fix: {bug.get('suggested_fix','')}"
                docs = search_codebase(query[:3000], repo_full_name, k=5)
                rag_blocks.append(
                    "\n".join(
                        [
                            f"{doc.metadata.get('file','')}:{doc.metadata.get('start_line',0)}-{doc.metadata.get('end_line',0)}\n{doc.page_content[:2000]}"
                            for doc in docs
                        ],
                    )[:7000]
                )
            rag_context = "\n\n".join(rag_blocks)[:12000]
            attempt_error_context = attempt_outputs[-1] if attempt_outputs else ""
            prompt_body = json.dumps(
                {
                    "repo_full_name": repo_full_name,
                    "pr_number": state["pr_number"],
                    "issues_raised": state.get("issues_raised", []),
                    "bugs_found": state.get("bugs_found", []),
                    "rag_context": rag_context,
                    "test_error_context": attempt_error_context,
                },
                ensure_ascii=False,
            )
            raw = await _draft_fix_llm(prompt_body)
            if is_blocked_response(raw) or raw.startswith(BLOCKED_PREFIX):
                blocked_error = "LLM call blocked by input security policy."
                test_output = (test_output or "") + blocked_error
                break
            fix_json = _extract_fix_plan_json(raw)
            plan = _FixPlan.model_validate_json(fix_json)
            for fp in plan.files:
                target_path = _safe_repo_relative_path(Path(clone_dir), fp.path)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(fp.content, encoding="utf-8")
            files_changed = [str(f.path).replace("\\", "/") for f in plan.files]
            ok, out = _run_tests(Path(clone_dir))
            test_output = out
            attempt_outputs.append(out)
            if ok:
                fix_diff = _git_diff(Path(clone_dir))
                break
        if fix_diff:
            pr_detail_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{state['pr_number']}"
            headers = {
                "Authorization": f"Bearer {installation_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                pr_detail_resp = await client.get(pr_detail_url, headers=headers)
                pr_detail_resp.raise_for_status()
                pr_detail_payload = pr_detail_resp.json()
                base_ref = str(pr_detail_payload["base"]["ref"])
                head_user = owner
                bot_branch = f"smart-pr-review-bot/fix-{state['pr_number']}-{int(asyncio.get_running_loop().time() * 1000)}"
                subprocess.run(
                    ["git", "checkout", "-B", bot_branch],
                    cwd=str(clone_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                subprocess.run(
                    ["git", "config", "user.name", "smart-pr-review-bot"],
                    cwd=str(clone_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                subprocess.run(
                    ["git", "config", "user.email", "smart-pr-review-bot@users.noreply.github.com"],
                    cwd=str(clone_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(clone_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                commit_message = f"chore: fix PR #{state['pr_number']} issues"
                commit_proc = subprocess.run(
                    ["git", "commit", "-m", commit_message],
                    cwd=str(clone_dir),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if commit_proc.returncode == 0:
                    push_proc = subprocess.run(
                        ["git", "push", "-u", "origin", bot_branch],
                        cwd=str(clone_dir),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                else:
                    push_proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=commit_proc.stderr)
                create_pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
                pr_title = f"[smart-pr-review-bot] Fix PR #{state['pr_number']}"
                pr_body = (
                    "## Smart fix drafted by smart-pr-review-agent\n"
                    f"Base branch: `{base_ref}`\n"
                    "This PR was created from the bot branch after local tests passed.\n"
                    f"\nOriginal PR: {state['pr_url']}\n"
                )
                create_payload = {
                    "title": pr_title,
                    "head": f"{head_user}:{bot_branch}",
                    "base": base_ref,
                    "body": pr_body,
                }
                create_pr_resp = await client.post(create_pr_url, headers=headers, json=create_payload)
                created = False
                fix_pr_url = ""
                fix_pr_number = None
                if create_pr_resp.status_code in (201, 200):
                    created = True
                    created_payload = create_pr_resp.json()
                    fix_pr_url = str(created_payload["html_url"])
                    fix_pr_number = created_payload["number"]
                else:
                    created = False
                merged = False
                merge_status = ""
                should_merge = state["mode"] in {"auto_pilot", "human_in_loop"} and str(state.get("approval_status", "")).lower() in {"approved", "tests_passed", "merged", "queued"}
                if created and should_merge and fix_pr_number is not None:
                    merge_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{fix_pr_number}/merge"
                    merge_payload = {"merge_method": "squash"}
                    merge_resp = await client.put(merge_url, headers=headers, json=merge_payload)
                    if merge_resp.status_code == 200:
                        merged = True
                        merge_status = "merged"
                    else:
                        merge_status = f"merge_failed:{merge_resp.status_code}"
                if fix_diff:
                    extra_info = []
                    if fix_pr_url:
                        extra_info.append(f"Fix PR: {fix_pr_url}")
                    if merge_status:
                        extra_info.append(f"Merge status: {merge_status}")
                    if extra_info:
                        test_output = (test_output or "") + "\n" + "\n".join(extra_info)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    updated = dict(state)
    updated["fix_patch"] = {
        "diff": fix_diff,
        "files_changed": files_changed,
        "test_output": test_output,
        "co_authored_by": co_authored_by,
    }
    updated["approval_status"] = "tests_passed" if fix_diff else "tests_failed"
    if fix_diff:
        updated["error"] = ""
    else:
        updated["error"] = blocked_error or updated.get("error", "")
    return updated
