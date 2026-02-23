# Contributing

Thanks for your interest in improving FieldFlow. This document outlines how to get a development environment running and how to contribute changes.

## Getting Started

1. **Fork & clone** the repository.
2. **Create a virtual environment** (Python 3.11 or newer is recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -e '.[dev,mcp]'
   ```

## Development Workflow

- Create a feature branch from `main`.
- Make your changes with clear, focused commits.
- Ensure the application still starts:
  ```bash
  fieldflow serve-http --reload
  ```
- Add or update documentation when behavior changes.
- If you add complex logic, include or update automated tests.

## Coding Standards

- Follow [PEP 8](https://peps.python.org/pep-0008/) and type annotate new Python code.
- Keep comments concise and helpful.
- Prefer dependency-light solutions; discuss large additions in an issue first.

## Checks

Run checks before opening a pull request:

```bash
ruff check fieldflow fieldflow_mcp tests
mypy fieldflow fieldflow_mcp
pytest
```

## Pull Requests

- Reference related issues in the pull request description.
- Provide a short summary of the change and any verification steps performed.
- Expect review feedback; we aim to respond promptly.

## Reporting Issues

Please use the issue templates when reporting bugs or requesting features. Include reproduction steps and environment details where possible.

We appreciate your help in making this project reliable and useful!
