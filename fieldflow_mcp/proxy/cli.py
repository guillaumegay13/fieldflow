"""CLI subcommands for the FieldFlow MCP proxy.

Surfaced as ``fieldflow mcp <subcommand>``. Subcommands:

* ``add``     register a new upstream and run the OAuth handshake (HTTP)
* ``list``    show registered upstreams
* ``remove``  delete an upstream entry and its stored tokens
* ``reauth``  re-run the OAuth handshake for an HTTP upstream
* ``serve``   run the proxy MCP server (stdio)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import Registry, UpstreamEntry, default_config_path
from .tokens import KeychainTokenStorage

logger = logging.getLogger(__name__)


def _parse_env(values: list[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise SystemExit(f"--env entries must be KEY=VALUE (got {raw!r})")
        key, _, value = raw.partition("=")
        env[key] = value
    return env


def _build_parser(prog: str = "fieldflow mcp") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Manage upstream MCP servers wrapped by FieldFlow.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Override the registry path (default: ~/.config/fieldflow/proxy.json)",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    add = sub.add_parser("add", help="Register an upstream MCP server")
    add.add_argument("namespace", help="Short prefix for tool names (e.g. 'posthog')")
    transport = add.add_mutually_exclusive_group(required=True)
    transport.add_argument("--url", help="HTTP+OAuth upstream URL (Streamable HTTP)")
    transport.add_argument(
        "--command",
        help="Shell command for stdio upstream (e.g. 'npx -y @posthog/mcp')",
    )
    add.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Environment variable for stdio upstream (repeatable)",
    )
    add.add_argument(
        "--scope",
        default=None,
        help="OAuth scope to request (HTTP upstream only)",
    )
    add.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the OAuth URL instead of opening a browser",
    )

    sub.add_parser("list", help="Show registered upstreams")

    remove = sub.add_parser("remove", help="Delete an upstream entry")
    remove.add_argument("namespace")

    reauth = sub.add_parser("reauth", help="Re-run OAuth handshake")
    reauth.add_argument("namespace")
    reauth.add_argument("--no-browser", action="store_true")
    reauth.add_argument("--scope", default=None)

    serve = sub.add_parser("serve", help="Run the proxy MCP server (stdio)")
    serve.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="Transport for the proxy itself (stdio only for now)",
    )

    return parser


async def _drive_oauth_handshake(
    entry: UpstreamEntry,
    *,
    open_browser: bool,
    scope: Optional[str],
) -> None:
    """Open a session against the upstream so the OAuth provider performs the
    full browser handshake and persists tokens."""

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    from .oauth import interactive_oauth_provider

    provider, _callback = await interactive_oauth_provider(
        entry, open_browser=open_browser, scope=scope
    )
    print(
        f"Connecting to {entry.url} (a browser window will open for "
        f"authorization)…",
        file=sys.stderr,
        flush=True,
    )

    async def _do_handshake() -> int:
        async with streamablehttp_client(entry.url, auth=provider) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return len(tools.tools)

    n_tools = await _do_handshake()
    print(
        f"Authorized '{entry.namespace}'. Discovered {n_tools} upstream tool(s).",
        file=sys.stderr,
        flush=True,
    )


def _cmd_add(args: argparse.Namespace, registry_path: Path) -> int:
    registry = Registry.load(registry_path)
    if args.namespace in registry.upstreams:
        print(
            f"Upstream '{args.namespace}' already exists. Use 'remove' first.",
            file=sys.stderr,
        )
        return 1

    if args.url:
        entry = UpstreamEntry(
            namespace=args.namespace, transport="http", url=args.url
        )
    else:
        command = args.command.split()
        env = _parse_env(args.env)
        entry = UpstreamEntry(
            namespace=args.namespace,
            transport="stdio",
            command=command,
            env=env,
        )

    if entry.transport == "http":
        try:
            asyncio.run(
                _drive_oauth_handshake(
                    entry, open_browser=not args.no_browser, scope=args.scope
                )
            )
        except Exception as exc:
            print(f"OAuth handshake failed: {exc}", file=sys.stderr)
            return 2

    registry.add(entry)
    registry.save(registry_path)
    print(f"Registered upstream '{entry.namespace}' ({entry.transport}).")
    return 0


def _cmd_list(_args: argparse.Namespace, registry_path: Path) -> int:
    registry = Registry.load(registry_path)
    if not registry.upstreams:
        print("No upstreams registered. Use 'fieldflow mcp add' to add one.")
        return 0
    print(json.dumps(
        {"upstreams": [e.to_dict() for e in registry.upstreams.values()]},
        indent=2,
    ))
    return 0


def _cmd_remove(args: argparse.Namespace, registry_path: Path) -> int:
    registry = Registry.load(registry_path)
    if args.namespace not in registry.upstreams:
        print(f"Upstream '{args.namespace}' not found.", file=sys.stderr)
        return 1
    registry.remove(args.namespace)
    registry.save(registry_path)
    KeychainTokenStorage(args.namespace).clear()
    print(f"Removed upstream '{args.namespace}' and cleared stored tokens.")
    return 0


def _cmd_reauth(args: argparse.Namespace, registry_path: Path) -> int:
    registry = Registry.load(registry_path)
    if args.namespace not in registry.upstreams:
        print(f"Upstream '{args.namespace}' not found.", file=sys.stderr)
        return 1
    entry = registry.get(args.namespace)
    if entry.transport != "http":
        print(
            f"Upstream '{args.namespace}' uses '{entry.transport}'; reauth is only for http.",
            file=sys.stderr,
        )
        return 1
    KeychainTokenStorage(args.namespace).clear()
    try:
        asyncio.run(
            _drive_oauth_handshake(
                entry, open_browser=not args.no_browser, scope=args.scope
            )
        )
    except Exception as exc:
        print(f"OAuth handshake failed: {exc}", file=sys.stderr)
        return 2
    print(f"Re-authorized '{args.namespace}'.")
    return 0


def _cmd_serve(_args: argparse.Namespace, _registry_path: Path) -> int:
    from .server import run_stdio

    asyncio.run(run_stdio())
    return 0


def main(argv: Optional[list[str]] = None, prog: str = "fieldflow mcp") -> int:
    parser = _build_parser(prog=prog)
    args = parser.parse_args(argv)
    registry_path = args.config or default_config_path()

    if args.subcommand == "add":
        return _cmd_add(args, registry_path)
    if args.subcommand == "list":
        return _cmd_list(args, registry_path)
    if args.subcommand == "remove":
        return _cmd_remove(args, registry_path)
    if args.subcommand == "reauth":
        return _cmd_reauth(args, registry_path)
    if args.subcommand == "serve":
        return _cmd_serve(args, registry_path)
    parser.error(f"Unknown subcommand: {args.subcommand}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
