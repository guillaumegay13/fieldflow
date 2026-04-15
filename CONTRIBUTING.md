# Contributing

Thanks for your interest in improving FieldFlow. The project is still early, so focused changes with clear tests are the easiest to review and merge.

## Supported Development Setup

FieldFlow supports Python 3.11 and 3.12. The CI pipeline runs linting and type checking on Python 3.12 and tests on both supported versions.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,mcp]'
```

Use quotes around extras in shells such as zsh.

## Project Scope

FieldFlow currently supports:

- OpenAPI-described REST APIs exposed as HTTP tool endpoints.
- OpenAPI-described REST APIs exposed as generated MCP tools.
- Response field filtering through the `fields` parameter.

FieldFlow does not yet wrap arbitrary existing MCP servers. If you want to work on that direction, please open an issue first so we can agree on the design.

## Development Workflow

1. Create a branch from the latest `main`.
2. Keep commits focused and use short imperative commit messages.
3. Add or update tests when behavior changes.
4. Update docs or examples when user-facing behavior changes.
5. Keep unrelated formatting and refactors out of the pull request.

## Coding Standards

- Use type hints for new Python code.
- Keep imports grouped as standard library, third-party, then local imports.
- Prefer small functions with explicit behavior over broad abstractions.
- Keep comments concise and reserve them for non-obvious logic.
- Avoid new runtime dependencies unless the benefit is clear and documented.
- Never commit secrets, API keys, tokens, or private OpenAPI specs.

## Checks

Run the same checks that CI runs before opening a pull request:

```bash
ruff check fieldflow fieldflow_mcp tests
black --check fieldflow fieldflow_mcp tests
mypy fieldflow fieldflow_mcp
pytest
python -m build
python -m pip check
```

During local development, it is fine to run narrower commands such as:

```bash
pytest tests/test_app.py -k fields
ruff check fieldflow/proxy.py tests/test_field_selector.py
```

Before requesting review, run the full check set or explain why a command could not be run.

## Pull Requests

Good pull requests include:

- A short summary of the behavior change.
- The reason the change is needed.
- Tests or manual verification commands.
- Notes about documentation, examples, or compatibility impact.
- Links to related issues when available.

Prefer draft pull requests while the shape is still changing. Mark a pull request ready for review once CI passes and the intended scope is stable.

## Reporting Issues

Use the issue templates for bugs and feature requests. Include:

- Your Python version and operating system.
- The OpenAPI spec or a minimal reproduction when possible.
- The command or tool invocation that failed.
- Expected behavior and actual behavior.
- Logs, stack traces, or curl output when relevant.

For security issues, do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).
