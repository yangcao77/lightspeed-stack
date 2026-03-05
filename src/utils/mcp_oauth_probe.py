"""Probe MCP server for OAuth and raise 401 with WWW-Authenticate when required."""

from typing import Optional
import aiohttp
from fastapi import HTTPException

from models.responses import UnauthorizedResponse

from log import get_logger

logger = get_logger(__name__)


async def probe_mcp_oauth_and_raise_401(
    url: str,
    authorization: Optional[str] = None,
) -> None:
    """Probe MCP endpoint and raise 401 so the client can perform OAuth.

    Performs an async GET to the given URL to obtain a WWW-Authenticate header,
    then raises HTTPException with status 401 and that header. If the probe
    fails (connection error, timeout), raises 401 without the header.

    Args:
        url: MCP server URL to probe.
        chain_from: Exception to chain the HTTPException from when
            the probe succeeds (e.g. the original AuthenticationError).

    Returns:
        None. Always raises an HTTPException.

    Raises:
        HTTPException: 401 with WWW-Authenticate when the probe succeeds, or
            401 without the header when the probe fails.
    """
    cause = f"MCP server at {url} requires OAuth"
    error_response = UnauthorizedResponse(cause=cause)
    headers: Optional[dict[str, str]] = (
        {"authorization": authorization} if authorization is not None else None
    )
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 401:
                    return
                www_auth = resp.headers.get("WWW-Authenticate")
                if www_auth is None:
                    logger.warning("No WWW-Authenticate header received from %s", url)
                    raise HTTPException(**error_response.model_dump())
                raise HTTPException(
                    **error_response.model_dump(),
                    headers={"WWW-Authenticate": www_auth},
                )
    except (aiohttp.ClientError, TimeoutError) as probe_err:
        logger.warning("OAuth probe failed for %s: %s", url, probe_err)
        raise HTTPException(**error_response.model_dump()) from probe_err
