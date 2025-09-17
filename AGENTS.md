# Repository Guidelines

## Project Structure & Module Organization
Core runtime code lives in `fieldflow/`, exported as the `fieldflow` package that builds FastAPI tooling on top of OpenAPI specs. MCP-specific utilities and the CLI wrapper stay in `fieldflow_mcp/`. Specs for local experimentation sit in `examples/`, while `tests/` holds pytest-based coverage for the HTTP proxy and MCP integration. Tooling metadata such as `pyproject.toml` and `requirements.txt` define install targets and extras (`.[dev]`, `.[mcp]`).

## Build, Test, and Development Commands
Bootstrap everything at once with `python -m venv .venv && source .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev,mcp]'`. After the command finishes, re-run `source .venv/bin/activate` in a fresh shell to work inside the environment. Launch the HTTP proxy via `fieldflow serve-http --reload` and switch to the MCP bridge with `fieldflow-mcp --transport stdio`. Run the full suite through `pytest`, or narrow focus using `pytest tests/test_app.py -k fields` during debugging.

## Coding Style & Naming Conventions
Python modules follow 4-space indentation, type hints, and descriptive snake_case names (`tooling.py`, `StubAsyncClient`). Run `ruff check fieldflow fieldflow_mcp tests` for linting and `black fieldflow fieldflow_mcp tests` for formatting before submitting. Keep imports ordered (stdlib, third-party, local) and prefer explicit re-exports in `fieldflow/__init__.py` for public APIs. Use `mypy fieldflow fieldflow_mcp` when touching type-heavy parsing code.

## Testing Guidelines
Tests live under `tests/test_*.py` and rely on `pytest` with `pytest-asyncio` for async flows. When adding endpoints or filters, mirror fixtures like `StubAsyncClient` to simulate upstream APIs, and assert both filtered payloads and proxy call metadata. Maintain parity between examples and tests; update `examples/*.yaml` whenever new schema assumptions are introduced.

## Commit & Pull Request Guidelines
Commit messages in this repo use short imperative summaries (e.g., `add proxy filter logging`). Group related changes together and include follow-up detail in the body only when necessary. Pull requests should describe behaviour changes, list relevant commands run (lint, tests), and mention impacted docs or specs. Link tracking issues when available and provide screenshots or curl output if the HTTP surface changes.

## Configuration & Deployment Notes
Environment variables drive runtime configuration: set `FIELD_FLOW_OPENAPI_SPEC_PATH` (or legacy `MCP_PROXY_OPENAPI_SPEC_PATH`) to target a spec and `FIELD_FLOW_TARGET_API_BASE_URL` when the spec lacks a server URL. Local servers default to `http://127.0.0.1:8000`; expose `--host 0.0.0.0` cautiously and avoid committing secrets in example specs.
