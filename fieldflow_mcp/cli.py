from __future__ import annotations

import argparse
import sys
from typing import Optional

from . import server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FieldFlow MCP command line interface")
    parser.add_argument("--name", default=None, help="Override the MCP server name")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport mode",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    if args_list and args_list[0] == "serve-mcp":
        args_list = args_list[1:]
    parser = _build_parser()
    args = parser.parse_args(args_list)

    server_instance = server.create_mcp_server(name=args.name)
    server_instance.run(transport=args.transport)


def legacy_entrypoint() -> None:
    argv = sys.argv[1:] or ["serve-mcp"]
    main(argv)


if __name__ == "__main__":
    main()
