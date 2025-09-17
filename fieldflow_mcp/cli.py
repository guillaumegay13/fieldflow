from __future__ import annotations

import argparse
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
    parser = _build_parser()
    args = parser.parse_args(argv)

    server_instance = server.create_mcp_server(name=args.name)
    server_instance.run(transport=args.transport)


if __name__ == "__main__":
    main()
