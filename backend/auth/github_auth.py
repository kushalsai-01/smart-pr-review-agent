from typing import Any

import httpx

from backend.config import Settings, get_settings


async def validate_oauth_token(token: str) -> dict[str, Any]:
    """Fetches the GitHub user profile for the supplied OAuth access token."""
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    ) as client:
        response = await client.get("/user")
        response.raise_for_status()
        return response.json()


def assert_app_credentials_match(settings: Settings) -> None:
    """Ensures stored OAuth application identifiers are non-empty strings."""
    if not settings.github_app_client_id.strip():
        raise ValueError("GITHUB_APP_CLIENT_ID is empty")
    if not settings.github_app_client_secret.strip():
        raise ValueError("GITHUB_APP_CLIENT_SECRET is empty")


def service_headers(settings: Settings | None) -> dict[str, str]:
    """Builds API headers that authenticate server-side GitHub requests."""
    resolved = settings or get_settings()
    return {
        "Authorization": f"Bearer {resolved.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
