from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import uvicorn

from .cli_runner import CLICommandError, inspect_json_command, run_json_command


def _add_run_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--field",
        dest="fields",
        action="append",
        default=[],
        help="Field selector to keep in the returned JSON payload. Repeat to keep multiple fields.",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=None,
        help="Limit the number of items kept from a root JSON array before field filtering.",
    )
    parser.add_argument(
        "wrapped_command",
        nargs=argparse.REMAINDER,
        help="Command to execute. Prefix with -- to separate FieldFlow options from the wrapped command.",
    )


def _execute_run_cli(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    wrapped_command = list(args.wrapped_command)
    if wrapped_command and wrapped_command[0] == "--":
        wrapped_command = wrapped_command[1:]
    if not wrapped_command:
        parser.error("a wrapped command is required after --")
    try:
        result = run_json_command(
            command=wrapped_command,
            fields=args.fields,
            max_items=args.max_items,
        )
    except ValueError as exc:
        parser.error(str(exc))
    except CLICommandError as exc:
        print(json.dumps(exc.payload, indent=2), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    print(json.dumps(result, indent=2))


def _add_inspect_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sample-items",
        type=int,
        default=100,
        help="Maximum number of root array items to sample while inferring selector paths.",
    )
    parser.add_argument(
        "wrapped_command",
        nargs=argparse.REMAINDER,
        help="Command to inspect. Prefix with -- to separate FieldFlow options from the wrapped command.",
    )


def _execute_inspect_cli(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    wrapped_command = list(args.wrapped_command)
    if wrapped_command and wrapped_command[0] == "--":
        wrapped_command = wrapped_command[1:]
    if not wrapped_command:
        parser.error("a wrapped command is required after --")
    try:
        result = inspect_json_command(
            command=wrapped_command,
            sample_items=args.sample_items,
        )
    except ValueError as exc:
        parser.error(str(exc))
    except CLICommandError as exc:
        print(json.dumps(exc.payload, indent=2), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc

    print(json.dumps(result, indent=2))


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

    run_cli_parser = subparsers.add_parser(
        "run-cli",
        help="Run a JSON-emitting CLI command and print a reduced result",
    )
    _add_run_cli_arguments(run_cli_parser)

    return parser


def _build_run_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FieldFlow CLI reducer for JSON-emitting commands"
    )
    _add_run_cli_arguments(parser)
    return parser


def _build_inspect_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FieldFlow CLI inspector for JSON-emitting commands"
    )
    _add_inspect_cli_arguments(parser)
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "serve-http":
        uvicorn.run(
            "fieldflow.http_app:app", host=args.host, port=args.port, reload=args.reload
        )
        return

    if args.command == "run-cli":
        _execute_run_cli(parser, args)
        return

    parser.error(f"Unknown command: {args.command}")


def run_cli_main(argv: Optional[list[str]] = None) -> None:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] == "inspect":
        parser = _build_inspect_cli_parser()
        args = parser.parse_args(argv_list[1:])
        _execute_inspect_cli(parser, args)
        return

    parser = _build_run_cli_parser()
    args = parser.parse_args(argv_list)
    _execute_run_cli(parser, args)


if __name__ == "__main__":
    main()
