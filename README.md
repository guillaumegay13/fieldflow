# FieldFlow

FieldFlow turns OpenAPI-described REST endpoints into selectively filtered tools. It generates Pydantic models and FastAPI routes that forward requests to the upstream API and return only the fields the caller asks for. An optional MCP layer exposes the same functionality to Model Context Protocol clients such as Claude Desktop.

## Features
- Discovers endpoints and schemas from OpenAPI 3.0 JSON or YAML files.
- Builds request/response Pydantic models dynamically, preserving aliases and
  optional fields.
- Generates FastAPI routes that accept parameters plus an optional `fields`
  list to slice responses.
- Proxies requests with `httpx`, automatically formatting URL paths and query
  parameters.
- Works with any OpenAPI-compliant spec, including nested schemas and refs.

## Project Layout
```
fieldflow/
  config.py          # Environment-based settings
  http_app.py        # FastAPI app factory
  openapi_loader.py  # JSON/YAML loader with PyYAML fallback
  proxy.py           # Async HTTP proxy that filters responses to requested fields
  spec_parser.py     # Schema parser and dynamic Pydantic model generator
  tooling.py         # FastAPI router builder for tool endpoints
fieldflow_mcp/
  server.py          # MCP server wrapper built on FastMCP
  cli.py             # CLI entry point for the MCP server
examples/
  jsonplaceholder_openapi.yaml  # Minimal sample spec
  pokeapi_openapi.yaml          # Larger spec for stress-testing
```

## Architecture

```mermaid
flowchart TD
  A[OpenAPI Spec (YAML/JSON)] --> B[openapi_loader.load_spec]
  B --> C[spec_parser: schemas, operations]
  C --> D[tooling: build_request_model/build_router]
  D --> E[FastAPI App (http_app.create_fastapi_app)]
  E --> F[/Generated /tools/{operation} routes/]

  %% Request path
  subgraph HTTP Path
    F --> G[proxy.APIProxy]
    G --> H[(Upstream REST API)]
    H --> G
    G --> I[Field Selector (fields param)]
    I --> J[Filtered JSON Response]
  end

  %% Optional MCP path
  C --> M[fieldflow_mcp.server: tool registry]
  M --> N[FastMCP Server (stdio)]
  N --> O[Claude Desktop / MCP Client]

  classDef core fill:#eef,stroke:#88a,stroke-width:1px;
  classDef io fill:#efe,stroke:#8a8,stroke-width:1px;
  class B,C,D,E,F,G,I,J core;
  class A,H,O io;
  class M,N io;
```

Key points:
- The FastAPI service is generated from the spec at startup; each operation becomes a `/tools/{operation}` route.
- Calls are proxied to the upstream API; responses are sliced to only requested `fields`.
- The MCP server (optional) exposes the same operations as tools over stdio for MCP clients.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e '.[mcp]'  # zsh users: quote to avoid globbing
# Alternatively: pip install -r requirements.txt
fieldflow serve-http --reload
```

OpenAPI specs are resolved from `FIELD_FLOW_OPENAPI_SPEC_PATH`. If the spec
includes a `servers` entry the first URL is used; otherwise set
`FIELD_FLOW_TARGET_API_BASE_URL`.

### Environment Variables

| Variable | Description | Default |
| --- | --- | --- |
| `FIELD_FLOW_OPENAPI_SPEC_PATH` | Path to the OpenAPI JSON/YAML file | `examples/jsonplaceholder_openapi.yaml` |
| `FIELD_FLOW_TARGET_API_BASE_URL` | Upstream REST API base URL (overrides spec `servers`) | _derived from spec_ |

## Example Tool Calls

### JSONPlaceholder (default)
Fetch only selected fields for a user:

```bash
curl -X POST http://127.0.0.1:8000/tools/get_user_info \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "fields": ["name", "email"]}'
```

List posts for a user, reducing each item to `id` and `title`:

```bash
curl -X POST http://127.0.0.1:8000/tools/list_posts \
  -H "Content-Type: application/json" \
  -d '{"userId": 1, "fields": ["id", "title"]}'
```

### PokeAPI
Switch to the richer PokeAPI specification:

```bash
export FIELD_FLOW_OPENAPI_SPEC_PATH=examples/pokeapi_openapi.yaml
fieldflow serve-http --reload
```

List the first few abilities:

```bash
curl -X POST http://127.0.0.1:8000/tools/ability_list \
  -H "Content-Type: application/json" \
  -d '{"limit": 5, "fields": ["results"]}'
```

Query a single ability by ID:

```bash
curl -X POST http://127.0.0.1:8000/tools/ability_read \
  -H "Content-Type: application/json" \
  -d '{"id": 65, "fields": ["name", "effect_entries"]}'
```

FastAPI automatically publishes documentation at
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs), letting you explore
and invoke the generated tool endpoints interactively.

## Command Line

Use the bundled CLI for a streamlined experience:

```bash
# Run the HTTP proxy
fieldflow serve-http --host 127.0.0.1 --port 8000

# Run the MCP server over stdio (ideal for Claude Desktop)
fieldflow-mcp
```

## Testing

Run the asynchronous test suite with pytest:

```bash
pip install -e .[dev]
pytest
```

## MCP Integration

To connect the server to Claude Desktop:

1. Install with the MCP extra (`pip install -e '.[mcp]'`).
2. Launch the stdio server: `fieldflow-mcp`.
3. In `claude_desktop_config.json`, add an entry under `mcpServers` pointing to the `fieldflow-mcp` command (or configure it via the Developer tab).
4. Claude will automatically list the generated tools and can invoke them during chats.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
instructions on setting up a development environment and submitting changes.

## License

This project is licensed under the [MIT License](LICENSE).
