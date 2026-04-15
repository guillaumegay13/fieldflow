# FieldFlow

FieldFlow turns OpenAPI-described REST endpoints into selectively filtered tools. It generates Pydantic models and FastAPI routes that forward requests to the upstream API and return only the fields the caller asks for. An optional MCP layer exposes the same functionality to Model Context Protocol clients such as Claude Desktop.

[![Voir la vidéo en HD](https://img.youtube.com/vi/-pgy0FICWpQ/maxresdefault.jpg)](https://www.youtube.com/watch?v=-pgy0FICWpQ)

## Features
- Discovers endpoints and schemas from OpenAPI 3.0 JSON or YAML files.
- Builds request/response Pydantic models dynamically, preserving aliases and
  optional fields.
- Generates FastAPI routes that accept parameters plus an optional `fields`
  list to slice responses.
- Proxies requests with `httpx`, automatically formatting URL paths and query
  parameters.
- Supports a two-step discovery flow (`discover-fields` + `fields`) designed
  for agent-native semantic field mapping with cached payload reuse.
- Works with any OpenAPI-compliant spec, including nested schemas and refs.

## Project Layout
```
fieldflow/
  config.py          # Environment-based settings
  http_app.py        # FastAPI app factory
  field_query.py     # Field discovery cache + optional AI query resolver
  openapi_loader.py  # JSON/YAML loader with PyYAML fallback
  proxy.py           # Async HTTP proxy that filters responses to requested fields
  spec_parser.py     # Schema parser and dynamic Pydantic model generator
  tooling.py         # FastAPI router builder for tool endpoints
fieldflow_mcp/
  server.py          # MCP server wrapper built on FastMCP
  cli.py             # CLI entry point for the MCP server
skills/
  fieldflow-smart-discovery/  # Agent workflow for discovery + cached field selection
examples/
  jsonplaceholder_openapi.yaml  # Minimal sample spec
  pokeapi_openapi.yaml          # Larger spec for stress-testing
```

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
| `FIELD_FLOW_DISCOVERY_ENABLED` | Enable `discover-fields` cache flow | `true` |
| `FIELD_FLOW_DISCOVERY_TTL_SECONDS` | Discovery cache TTL (seconds) | `180` |
| `FIELD_FLOW_DISCOVERY_MAX_ENTRIES` | Max in-memory discovery entries | `256` |
| `FIELD_FLOW_DISCOVERY_MAX_CANDIDATES` | Max candidate selectors returned by discovery | `400` |
| `FIELD_FLOW_DISCOVERY_PREVIEW_MAX_CHARS` | Max JSON preview chars returned by discovery | `12000` |
| `FIELD_FLOW_DISCOVERY_PATH_MAX_DEPTH` | Max traversal depth for candidate extraction | `8` |
| `FIELD_FLOW_DISCOVERY_LIST_SAMPLE_SIZE` | Max sampled list items during candidate extraction | `10` |
| `FIELD_FLOW_FIELD_QUERY_ENABLED` | Enable optional AI-backed `field_query` fallback | `false` |
| `FIELD_FLOW_FIELD_QUERY_MODEL` | Model id for field query resolution | _unset_ |
| `FIELD_FLOW_FIELD_QUERY_API_KEY` | API key for the model provider (fallback: `OPENAI_API_KEY`) | _unset_ |
| `FIELD_FLOW_FIELD_QUERY_API_BASE_URL` | OpenAI-compatible API base URL | `https://api.openai.com/v1` |

### Authentication

FieldFlow supports secure API authentication through environment variables. All credentials are handled securely with automatic sanitization in logs and error messages.

#### Simple Authentication
```bash
# Bearer token (OAuth 2.0, JWT)
export FIELDFLOW_AUTH_TYPE=bearer
export FIELDFLOW_AUTH_VALUE=your-token-here

# API Key
export FIELDFLOW_AUTH_TYPE=apikey
export FIELDFLOW_AUTH_HEADER=X-API-Key  # Optional, defaults to X-API-Key
export FIELDFLOW_AUTH_VALUE=your-api-key-here

# Basic authentication
export FIELDFLOW_AUTH_TYPE=basic
export FIELDFLOW_AUTH_VALUE=base64-encoded-credentials
```

#### OpenAPI Security Schemes
When your OpenAPI spec defines security schemes, FieldFlow automatically uses them:
```yaml
components:
  securitySchemes:
    BearerAuth:
      type: http
      scheme: bearer
    ApiKeyAuth:
      type: apiKey
      in: header
      name: X-API-Key
```

With security schemes, provide credentials using the scheme name:
```bash
export FIELDFLOW_AUTH_BEARERAUTH_VALUE=your-bearer-token
export FIELDFLOW_AUTH_APIKEYAUTH_VALUE=your-api-key
```

**Security features:**
- Credentials are never logged or stored
- Auth headers are sanitized in all error messages
- Memory-safe handling with immediate credential clearing
- Environment-only configuration (no hardcoded secrets)

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

### Nested field selectors
Request deeply nested data with a JSONPath-lite syntax tailored for LLMs:

- Use dots (`damage_relations.double_damage_from`) to traverse objects.
- Append `[]` to map over every element in a list (`moves[].move.name`).
- Mix top-level and nested selectors in the same request; missing branches are skipped.

Example with the PokeAPI spec:

```bash
curl -X POST http://127.0.0.1:8000/tools/pokemon_read \
  -H "Content-Type: application/json" \
  -d '{"id": 150, "fields": ["name", "types[].type.name", "stats.attack.base_stat"]}'
```

The proxy trims everything except Mewtwo's name, each type name, and the attack stat. Invalid selectors (for example `moves[0].move`) return a 422 error before the upstream API is called.

### Agent-native smart discovery (recommended)
When you do not know exact field names, use the discovery flow:

1. Call `/tools/<operation>/discover-fields` with normal operation params.
2. Let your agent map the user intent to selectors from returned `candidates`.
3. Call `/tools/<operation>` with `fields` and the returned `discovery_id`.

Step 1: discover candidates and cache payload:

```bash
curl -X POST http://127.0.0.1:8000/tools/get_user_info/discover-fields \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1}'
```

Step 2: request filtered response using cached `discovery_id`:

```bash
curl -X POST http://127.0.0.1:8000/tools/get_user_info \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "discovery_id": "DISCOVERY_ID_FROM_STEP_1", "fields": ["email", "id"]}'
```

Why this flow is agent-friendly:
- No extra model call required inside FieldFlow.
- Second call can reuse cached upstream payload (lower latency/cost).
- Returned fields are still strictly validated by FieldFlow selectors.

### Optional AI fallback (`field_query`)
If you still want server-side model-based mapping, enable `field_query`:

```bash
export FIELD_FLOW_FIELD_QUERY_ENABLED=true
export FIELD_FLOW_FIELD_QUERY_MODEL=gpt-4.1-mini
export FIELD_FLOW_FIELD_QUERY_API_KEY=your-api-key
```

Then call an operation with `field_query`:

```bash
curl -X POST http://127.0.0.1:8000/tools/get_user_info \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "field_query": "contact details", "field_query_limit": 5}'
```

Notes:
- `fields` takes precedence over `field_query` when both are provided.
- `field_query` is optional and disabled by default.
- The model can only select from fields present in the real response payload.
- If model resolution is unavailable or returns no valid fields, FieldFlow returns
  the full response instead of failing.
- Inferred selectors follow the same syntax (`.` and `[]`), for example
  `moves[].move.name`.

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
2. Claude Desktop launches configured MCP servers on startup—no need to run `fieldflow-mcp` manually.
3. Open Claude Desktop → Settings → Developer → Modify Config, then paste a configuration that points to the FieldFlow server (see `claude_config_example/claude_desktop_config.json`).
4. For additional details, review the Model Context Protocol guide: https://modelcontextprotocol.io/docs/develop/connect-local-servers.
5. Claude will automatically list the generated tools and can invoke them during chats once the config is saved.

## Agent Skill (Claude Code/OpenClaw/Any MCP Agent)

This repository ships a reusable discovery skill:

- `skills/fieldflow-smart-discovery/SKILL.md`

It standardizes a two-step workflow:
1. Call `<tool>__discover_fields`.
2. Call `<tool>` with `fields` + `discovery_id`.

Use it as the behavior template for Claude Code, OpenClaw, or any MCP-capable
agent to get semantic field selection without extra model calls inside
FieldFlow.

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
instructions on setting up a development environment and submitting changes.

## License

This project is licensed under the [MIT License](LICENSE).
