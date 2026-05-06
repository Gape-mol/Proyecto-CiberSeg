from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


# Wraps GitHub API calls with retries and pagination.
class GitHubClient:
    BASE_URL = "https://api.github.com"

    # Initializes the API client with a token.
    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._limiter = asyncio.Semaphore(10)

    # Streams repositories for a GitHub organization.
    async def list_org_repos(
        self,
        org: str,
        visibility: str = "all",
        per_page: int = 100,
        max_results: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        url: str | None = f"{self.BASE_URL}/orgs/{org}/repos"
        params: dict[str, Any] = {
            "per_page": per_page,
            "type": visibility,
            "sort": "pushed",
            "direction": "desc",
        }

        page = 0
        yielded = 0
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            while url:
                page += 1
                logger.debug(f"  API página {page}: {url}")
                response = await self._get_with_retry(client, url, params=params)
                repos = response.json()

                if not isinstance(repos, list):
                    error = repos.get("message", "Unknown error")
                    raise RuntimeError(f"Error de GitHub API: {error}")

                for repo in repos:
                    if not isinstance(repo, dict):
                        raise RuntimeError("GitHub API devolvió un repo con formato inválido")
                    yield repo
                    yielded += 1
                    if max_results and yielded >= max_results:
                        return

                url = self._next_link(response.headers.get("Link", ""))
                params = {}

    # Fetches organization metadata from GitHub.
    async def get_org(self, org: str) -> dict[str, Any]:
        async with httpx.AsyncClient(headers=self._headers, timeout=30) as client:
            r = await self._get_with_retry(client, f"{self.BASE_URL}/orgs/{org}")
            payload = r.json()
            if not isinstance(payload, dict):
                raise RuntimeError("GitHub API devolvió una organización con formato inválido")
            return cast(dict[str, Any], payload)

    # Validates the token and organization before running.
    async def preflight_check(self, org: str) -> None:
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            r = await client.get(f"{self.BASE_URL}/rate_limit")
            if r.status_code == 401:
                raise RuntimeError(
                    "❌  Token de GitHub inválido o expirado.\n"
                    "    Verificá GITHUB_TOKEN en /workspace/.env (sin comillas)."
                )
            r.raise_for_status()
            rate = r.json()["resources"]["core"]
            logger.info(
                f"✅  Token válido — rate limit: {rate['remaining']}/{rate['limit']} "
                f"requests disponibles"
            )

            r2 = await client.get(f"{self.BASE_URL}/orgs/{org}")
            if r2.status_code == 404:
                raise RuntimeError(
                    f"❌  Organización '{org}' no encontrada en GitHub.\n"
                    f"    Verificá GITHUB_ORG en /workspace/.env."
                )
            if r2.status_code == 403:
                raise RuntimeError(
                    f"❌  Sin permiso para acceder a '{org}' (403).\n"
                    f"    El token necesita scope 'read:org'."
                )
            r2.raise_for_status()
            org_data = r2.json()
            logger.info(
                f"✅  Organización encontrada: {org_data.get('login')} "
                f"— {org_data.get('public_repos', '?')} repos públicos"
            )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        async with self._limiter:
            response = await client.get(url, **kwargs)

            if response.status_code == 429 or (
                response.status_code == 403
                and "rate limit" in response.text.lower()
            ):
                reset_at = int(response.headers.get("X-RateLimit-Reset", 0))
                wait = max(reset_at - int(datetime.now(UTC).timestamp()), 1)
                logger.warning(f"Rate limit alcanzado. Esperando {wait}s…")
                await asyncio.sleep(wait)
                response = await client.get(url, **kwargs)

            response.raise_for_status()
            return response

    # Parses the GitHub Link header to get the next page URL.
    @staticmethod
    def _next_link(link_header: str) -> str | None:
        if not link_header:
            return None
        for part in link_header.split(","):
            url_part, *rel_parts = part.strip().split(";")
            if any('rel="next"' in r for r in rel_parts):
                return url_part.strip().strip("<>")
        return None
