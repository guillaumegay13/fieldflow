from __future__ import annotations

import argparse
from typing import Optional

import uvicorn



def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="FieldFlow command line interface")
    subparsers = parser.add_subparsers(dest="command", required=True)

    http_parser = subparsers.add_parser(
        "serve-http", help="Run the FieldFlow FastAPI server"
    )
    http_parser.add_argument(
        "--host", default="127.0.0.1", help="Host interface for the HTTP server"
    )
    http_parser.add_argument(
        "--port", type=int, default=8000, help="Port for the HTTP server"
    )
    http_parser.add_argument(
        "--reload", action="store_true", help="Enable autoreload (development only)"
    )

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve-http":
        uvicorn.run(
            "fieldflow.http_app:app", host=args.host, port=args.port, reload=args.reload
        )
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
