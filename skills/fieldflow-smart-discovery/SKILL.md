---
name: fieldflow-smart-discovery
description: Use FieldFlow discovery tools to map fuzzy field requests to exact selectors in Claude Code, OpenClaw, and other MCP agents without additional model calls inside FieldFlow.
---

# FieldFlow Smart Discovery

Use this skill when:
- The user asks for natural-language, fuzzy, or semantic field selection.
- Exact response field names are unknown.

## Workflow

1. Identify the target FieldFlow tool (for example `get_user_info`).
2. Call the matching discovery tool first: `<tool>__discover_fields`.
3. Read `candidates` and `payload_preview` from discovery output.
4. Map user intent to selectors from `candidates` only.
5. Prefer recall over under-selection. Include supporting identifiers (`id`, names, status) when relevant.
6. Call `<tool>` with:
   - `fields`: selected selectors
   - `discovery_id`: from discovery output
7. If response is `422` with expired/unknown discovery id, rerun step 2.

## Rules

- Never invent selectors not present in `candidates`.
- Keep selector syntax valid (`.` for nesting, `[]` for list wildcard).
- If selection confidence is low, include slightly more context rather than less.
- If the user explicitly asks for minimal payload, bias toward fewer fields.

## Agent Notes

- Claude Code: run discovery tool first, then main tool with `discovery_id`.
- OpenClaw: same two-step flow applies; only tool invocation format changes.
- Any MCP agent: the workflow is transport-agnostic.
