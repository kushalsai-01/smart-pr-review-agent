from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Any, Final

import httpx

from langchain_core.messages import HumanMessage
from langchain_groq import ChatGroq

from backend.config import settings
from backend.models.state import LLMProvider

logger = logging.getLogger("llm_security")

BLOCKED_PREFIX: Final[str] = "__LLM_BLOCKED__:"

_PROMPT_INJECTION_PATTERNS: Final[list[re.Pattern[str]]] = [
    re.compile(r"\bignore previous instructions\b", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"\bdeveloper message\b", re.IGNORECASE),
    re.compile(r"\bact as\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bdisregard\b", re.IGNORECASE),
    re.compile(r"\bprompt injection\b", re.IGNORECASE),
]

_EMAIL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b",
    re.IGNORECASE,
)
_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(\+?\d{1,3}[-.\s]?)?(\(?\d{2,3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)
_CREDIT_CARD_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:\d[ -]*?){13,19}\b",
)


@dataclass(frozen=True)
class SecurityScanResult:
    """Holds security findings from prompt scanning."""

    unsafe: bool
    flags: list[str]


@dataclass(frozen=True)
class QualityScore:
    """Holds a lightweight response quality estimate."""

    score: float


def _approx_token_count(text: str) -> int:
    """Estimates tokens by splitting on whitespace."""
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, len(cleaned.split()))


def _luhn_checksum(card_number: str) -> bool:
    """Validates a numeric string with a Luhn checksum."""
    digits = [int(ch) for ch in card_number if ch.isdigit()]
    if len(digits) < 12:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d = d * 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _looks_like_credit_card(candidate: str) -> bool:
    """Checks whether a match is likely a real credit card."""
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 13 or len(digits) > 19:
        return False
    return _luhn_checksum(digits)


def scan_prompt(prompt: str) -> SecurityScanResult:
    """Scans a prompt for prompt injection and PII patterns."""
    flags: list[str] = []
    injection_hits = [p.pattern for p in _PROMPT_INJECTION_PATTERNS if p.search(prompt)]
    if injection_hits:
        flags.append("prompt_injection")
    email_hits = bool(_EMAIL_PATTERN.search(prompt))
    if email_hits:
        flags.append("email")
    phone_hits = bool(_PHONE_PATTERN.search(prompt))
    if phone_hits:
        flags.append("phone")
    cc_hits = []
    for m in _CREDIT_CARD_PATTERN.finditer(prompt):
        value = m.group(0)
        if _looks_like_credit_card(value):
            cc_hits.append(value)
    if cc_hits:
        flags.append("credit_card")
    unsafe = bool(flags)
    return SecurityScanResult(unsafe=unsafe, flags=flags)


def _is_json_like(text: str) -> bool:
    """Checks whether a string resembles JSON output."""
    t = text.strip()
    if not (t.startswith("{") and t.endswith("}")):
        return False
    try:
        json.loads(t)
        return True
    except Exception:
        return False


def evaluate_response_quality(prompt: str, response: str) -> QualityScore:
    """Scores response quality using simple heuristics."""
    score = 0.2
    if response and len(response) > 60:
        score += 0.3
    if _is_json_like(response):
        score += 0.3
    if "error" in response.lower():
        score -= 0.1
    if "blocked" in response.lower():
        score -= 0.2
    score = max(0.0, min(1.0, score))
    _ = _approx_token_count(prompt)
    return QualityScore(score=score)


def _blocked_message(reason: str) -> str:
    """Builds a deterministic blocked message payload."""
    return f"{BLOCKED_PREFIX}{reason}"


def is_blocked_response(response: str) -> bool:
    """Checks whether a response is blocked by the security layer."""
    return response.strip().startswith(BLOCKED_PREFIX)


_THREAD_LLM_PROVIDER: ContextVar[str] = ContextVar("llm_provider", default="groq")
_THREAD_LLM_API_KEY: ContextVar[str | None] = ContextVar("llm_api_key", default=None)
_THREAD_LLM_MODEL: ContextVar[str | None] = ContextVar("llm_model", default=None)


def set_llm_context(provider: LLMProvider, api_key: str | None, model: str | None) -> None:
    """Sets per-task LLM credentials for secure_llm_call."""
    _THREAD_LLM_PROVIDER.set(provider)
    _THREAD_LLM_API_KEY.set(api_key)
    _THREAD_LLM_MODEL.set(model)


def clear_llm_context() -> None:
    """Clears per-task LLM credentials for secure_llm_call."""
    _THREAD_LLM_PROVIDER.set("groq")
    _THREAD_LLM_API_KEY.set(None)
    _THREAD_LLM_MODEL.set(None)


async def _call_groq(prompt: str, api_key: str | None, model: str | None) -> str:
    """Calls Groq using LangChain wrapper."""
    groq_api_key = api_key or settings.groq_api_key
    used_model = model or "llama-3.3-70b"
    llm = ChatGroq(groq_api_key=groq_api_key, model=used_model, temperature=0.2)
    llm_result = await llm.ainvoke([HumanMessage(content=prompt)])
    return str(getattr(llm_result, "content", "")) or str(llm_result)


async def _call_claude(prompt: str, api_key: str, model: str | None) -> str:
    """Calls Anthropic Claude via HTTP API."""
    used_model = model or "claude-3-5-sonnet-latest"
    body: dict[str, Any] = {
        "model": used_model,
        "max_tokens": 1024,
        "temperature": 0.2,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    content = payload.get("content") or []
    for item in content:
        if item.get("type") == "text" and isinstance(item.get("text"), str):
            return item["text"]
    return json.dumps(payload)


async def _call_gemini(prompt: str, api_key: str, model: str | None) -> str:
    """Calls Google Gemini via HTTP API."""
    used_model = model or "gemini-1.5-pro-latest"
    model_id = used_model
    if model_id.startswith("models/"):
        model_id = model_id.split("/", 1)[1]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        payload = resp.json()
    candidates = payload.get("candidates") or []
    if not candidates:
        return json.dumps(payload)
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            return str(part["text"])
    return json.dumps(payload)


async def secure_llm_call(
    prompt: str,
    thread_id: str | None = None,
    provider: LLMProvider | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> str:
    """Runs prompt scanning, calls the LLM based on provider, and evaluates response quality."""
    start = time.perf_counter()
    scan = scan_prompt(prompt)
    latency_ms = int((time.perf_counter() - start) * 1000)
    token_est = _approx_token_count(prompt)
    effective_provider = provider or _THREAD_LLM_PROVIDER.get()
    effective_model = model or _THREAD_LLM_MODEL.get()
    effective_key = api_key if api_key is not None else _THREAD_LLM_API_KEY.get()

    logger.info(
        "llm_security.scan latency_ms=%s token_est=%s unsafe=%s flags=%s provider=%s thread_id=%s",
        latency_ms,
        token_est,
        scan.unsafe,
        ",".join(scan.flags),
        effective_provider,
        thread_id or "",
    )

    if scan.unsafe:
        return _blocked_message(",".join(scan.flags) if scan.flags else "unsafe")

    llm_start = time.perf_counter()
    if effective_provider == "groq":
        response = await _call_groq(prompt, effective_key, effective_model)
    elif effective_provider == "claude":
        if not effective_key:
            return _blocked_message("missing_api_key")
        response = await _call_claude(prompt, effective_key, effective_model)
    elif effective_provider == "gemini":
        if not effective_key:
            return _blocked_message("missing_api_key")
        response = await _call_gemini(prompt, effective_key, effective_model)
    else:
        return _blocked_message("unsupported_provider")

    eval_score = evaluate_response_quality(prompt, response).score
    latency_total_ms = int((time.perf_counter() - llm_start) * 1000)
    token_est_resp = _approx_token_count(response)
    logger.info(
        "llm_security.call latency_ms=%s token_est_prompt=%s token_est_resp=%s quality_score=%.3f provider=%s",
        latency_total_ms,
        token_est,
        token_est_resp,
        eval_score,
        effective_provider,
    )
    return response

