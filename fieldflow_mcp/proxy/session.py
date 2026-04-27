"""Per-upstream MCP client sessions for the proxy."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator, Optional

import mcp.types as mcp_types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .config import Registry, UpstreamEntry
from .oauth import runtime_oauth_provider

logger = logging.getLogger(__name__)


@asynccontextmanager
async def open_upstream(
    entry: UpstreamEntry,
) -> AsyncGenerator[ClientSession, None]:
    """Open a long-lived MCP client session against a single upstream."""

    if entry.transport == "http":
        if not entry.url:
            raise ValueError(f"Upstream '{entry.namespace}' missing url")
        auth = await runtime_oauth_provider(entry)
        async with streamablehttp_client(entry.url, auth=auth) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    if entry.transport == "stdio":
        if not entry.command:
            raise ValueError(f"Upstream '{entry.namespace}' missing command")
        params = StdioServerParameters(
            command=entry.command[0],
            args=list(entry.command[1:]),
            env=dict(entry.env) if entry.env else None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    raise ValueError(f"Unknown transport '{entry.transport}'")


class UpstreamPool:
    """Holds one live :class:`ClientSession` per registered upstream and
    routes ``list_tools`` / ``call_tool`` requests to the right one.

    Upstreams that fail to start are logged and skipped — the proxy keeps
    serving the rest, and degraded upstreams surface as missing tools rather
    than bringing the whole proxy down.
    """

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.sessions: dict[str, ClientSession] = {}
        self.errors: dict[str, str] = {}
        self._stack: Optional[AsyncExitStack] = None

    async def __aenter__(self) -> "UpstreamPool":
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for namespace, entry in self.registry.upstreams.items():
            try:
                session = await self._stack.enter_async_context(open_upstream(entry))
            except Exception as exc:  # pragma: no cover - logged for ops
                logger.exception(
                    "Failed to start upstream '%s'; skipping", namespace
                )
                self.errors[namespace] = str(exc)
                continue
            self.sessions[namespace] = session
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        assert self._stack is not None
        try:
            await self._stack.__aexit__(*exc_info)
        finally:
            self._stack = None

    async def list_all_tools(self) -> list[tuple[str, mcp_types.Tool]]:
        out: list[tuple[str, mcp_types.Tool]] = []
        for namespace, session in self.sessions.items():
            result = await session.list_tools()
            for tool in result.tools:
                out.append((namespace, tool))
        return out

    async def call_tool(
        self,
        namespace: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> mcp_types.CallToolResult:
        if namespace not in self.sessions:
            err = self.errors.get(namespace, "upstream not connected")
            return mcp_types.CallToolResult(
                content=[
                    mcp_types.TextContent(
                        type="text",
                        text=f"Upstream '{namespace}' is unavailable: {err}",
                    )
                ],
                isError=True,
            )
        session = self.sessions[namespace]
        return await session.call_tool(tool_name, arguments=arguments)
