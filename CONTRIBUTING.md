# Contributing

Thanks for your interest in improving the Dynamic MCP REST Proxy! This document outlines how to get a development environment running and how to contribute changes.

## Getting Started

1. **Fork & clone** the repository.
2. **Create a virtual environment** (Python 3.11 or newer is recommended):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. **Install development extras (optional)**. For linting and formatting we suggest:
   ```bash
   pip install black ruff mypy
   ```

## Development Workflow

- Create a feature branch from `main`.
- Make your changes with clear, focused commits.
- Ensure the application still starts:
  ```bash
  fieldflow serve-http --reload
  ```
- Add or update documentation when behavior changes.
- If you add complex logic, please include automated tests or describe manual test steps in the pull request.

## Coding Standards

- Follow [PEP 8](https://peps.python.org/pep-0008/) and type annotate new Python code.
- Keep comments concise and helpful.
- Prefer dependency-light solutions; discuss large additions in an issue first.

## Running Tests

Formal tests are not yet included. If you add a test suite, document how to run it here. Meanwhile, please run manual smoke tests against the example specs before submitting a pull request.

## Pull Requests

- Reference related issues in the pull request description.
- Provide a short summary of the change and any verification steps performed.
- Expect review feedback; we aim to respond promptly.

## Reporting Issues

Please use the issue templates when reporting bugs or requesting features. Include reproduction steps and environment details where possible.

We appreciate your help in making this project reliable and useful!
