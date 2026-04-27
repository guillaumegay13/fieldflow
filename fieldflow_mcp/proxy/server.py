"""FieldFlow proxy MCP server.

Boots an :class:`UpstreamPool`, then exposes one wrapper tool per upstream
tool with name ``{namespace}__{tool_name}`` and an injected ``fields``
parameter. On call, forwards to the upstream and filters the JSON portion of
the response in-place.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

import mcp.types as mcp_types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from fieldflow.proxy import (
    FieldSelectorError,
    build_selector_tree,
    filter_with_selector_tree,
)

from .config import Registry, default_config_path
from .session import UpstreamPool

logger = logging.getLogger(__name__)

NAMESPACE_SEP = "__"
SERVER_NAME = "fieldflow-proxy"
INSTRUCTIONS = (
    "FieldFlow MCP proxy. Each tool wraps a tool from a registered upstream MCP "
    "server. Pass `fields` (list of dot-path selectors, e.g. ['data.id', 'meta']) "
    "to filter the response and reduce token usage. Omit `fields` to get the full "
    "upstream response."
)

FIELDS_PARAM = "fields"

_FIELDS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Optional list of dot-path selectors to keep in the response "
        "(e.g. 'data.results[].id'). Use '[]' to descend into list items. "
        "Omit to return the full upstream response unchanged."
    ),
}


def _wrap_tool(namespace: str, tool: mcp_types.Tool) -> mcp_types.Tool:
    """Take an upstream tool and produce the proxied version: namespaced
    name, injected ``fields`` input parameter, identical output schema."""

    input_schema: dict[str, Any] = dict(tool.inputSchema or {"type": "object"})
    properties = dict(input_schema.get("properties") or {})
    if FIELDS_PARAM in properties:
        logger.warning(
            "Upstream '%s' tool '%s' already declares a 'fields' parameter; "
            "the proxy's filter is applied after the upstream returns.",
            namespace,
            tool.name,
        )
    else:
        properties[FIELDS_PARAM] = _FIELDS_SCHEMA
    input_schema["properties"] = properties
    input_schema.setdefault("type", "object")

    description = tool.description or ""
    proxied_description = (
        f"[via fieldflow:{namespace}] {description}".strip()
        if description
        else f"[via fieldflow:{namespace}] {tool.name}"
    )

    return mcp_types.Tool(
        name=f"{namespace}{NAMESPACE_SEP}{tool.name}",
        title=tool.title,
        description=proxied_description,
        inputSchema=input_schema,
        outputSchema=tool.outputSchema,
        annotations=tool.annotations,
        meta=tool.meta,
    )


def _split_namespaced(name: str) -> tuple[str, str]:
    if NAMESPACE_SEP not in name:
        raise ValueError(f"Tool name '{name}' is missing namespace prefix")
    namespace, _, tool_name = name.partition(NAMESPACE_SEP)
    if not namespace or not tool_name:
        raise ValueError(f"Malformed namespaced tool '{name}'")
    return namespace, tool_name


def _filter_payload(payload: Any, fields: list[str]) -> Any:
    """Filter a JSON-decoded payload by dot-path selectors. Returns the
    filtered payload, or the original if selectors are malformed (we never
    want filtering to break a working call)."""

    try:
        tree = build_selector_tree(fields)
    except FieldSelectorError as exc:
        logger.warning("Invalid fields selector %s: %s", fields, exc)
        return payload
    return filter_with_selector_tree(payload, tree)


def _filter_text_content(
    content: mcp_types.TextContent, fields: list[str]
) -> mcp_types.TextContent:
    text = content.text
    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        return content
    if not isinstance(decoded, (dict, list)):
        return content
    filtered = _filter_payload(decoded, fields)
    return mcp_types.TextContent(
        type="text",
        text=json.dumps(filtered, ensure_ascii=False),
        annotations=content.annotations,
    )


def _filter_result(
    result: mcp_types.CallToolResult, fields: list[str]
) -> mcp_types.CallToolResult:
    if result.isError:
        return result

    new_content: list[mcp_types.ContentBlock] = []
    for block in result.content:
        if isinstance(block, mcp_types.TextContent):
            new_content.append(_filter_text_content(block, fields))
        else:
            new_content.append(block)

    new_structured = result.structuredContent
    if new_structured is not None:
        filtered = _filter_payload(new_structured, fields)
        if isinstance(filtered, dict):
            new_structured = filtered

    return mcp_types.CallToolResult(
        content=new_content,
        structuredContent=new_structured,
        isError=False,
        meta=result.meta,
    )


def create_proxy_server(registry: Optional[Registry] = None) -> Server:
    """Build a configured (but not yet running) proxy MCP server."""

    registry = registry or Registry.load()

    @asynccontextmanager
    async def lifespan(_server: Server) -> AsyncGenerator[UpstreamPool, None]:
        async with UpstreamPool(registry) as pool:
            connected = sorted(pool.sessions.keys())
            failed = sorted(pool.errors.keys())
            logger.info(
                "fieldflow-proxy ready: connected=%s failed=%s",
                connected,
                failed,
            )
            yield pool

    server: Server = Server(
        name=SERVER_NAME,
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
    )

    @server.list_tools()
    async def list_tools() -> list[mcp_types.Tool]:
        pool: UpstreamPool = server.request_context.lifespan_context  # type: ignore[assignment]
        upstream_tools = await pool.list_all_tools()
        return [_wrap_tool(ns, tool) for ns, tool in upstream_tools]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> mcp_types.CallToolResult:
        pool: UpstreamPool = server.request_context.lifespan_context  # type: ignore[assignment]
        namespace, tool_name = _split_namespaced(name)

        forwarded = dict(arguments or {})
        fields_value = forwarded.pop(FIELDS_PARAM, None)

        result = await pool.call_tool(namespace, tool_name, forwarded)

        if fields_value:
            if not isinstance(fields_value, list) or not all(
                isinstance(f, str) for f in fields_value
            ):
                logger.warning(
                    "Ignoring non-list/non-string fields argument: %r", fields_value
                )
                return result
            return _filter_result(result, fields_value)
        return result

    return server


async def run_stdio(registry_path: Optional[str] = None) -> None:
    registry = Registry.load(default_config_path() if registry_path is None else None)
    server = create_proxy_server(registry)
    init_options = server.create_initialization_options()
    async with stdio_server() as (read, write):
        await server.run(read, write, init_options)
