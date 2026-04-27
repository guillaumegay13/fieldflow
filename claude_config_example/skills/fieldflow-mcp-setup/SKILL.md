---
name: fieldflow-mcp-setup
description: Set up FieldFlow MCP proxy to wrap and field-filter one or more upstream MCP servers (PostHog, Supabase, etc.) so agent tool calls return only the JSON fields requested. Use when the user asks to install fieldflow, add an upstream MCP behind fieldflow, save tokens on MCP responses, register a new MCP via OAuth, or wire field filtering in front of existing MCP servers.
---

# FieldFlow MCP setup

Walk the user through installing fieldflow, registering one or more upstream MCP servers behind it via OAuth (or stdio), and wiring the proxy into Claude Code so every namespaced tool gains a `fields` selector.

## Preflight

Run these in parallel:

```bash
which pipx
which fieldflow
fieldflow mcp --help 2>&1 | head -3
```

- If `pipx` is missing, install it: `brew install pipx && pipx ensurepath`. Tell the user to reopen their shell so PATH picks up `~/.local/bin`.
- If `fieldflow` is missing or `fieldflow mcp --help` errors with "invalid choice: 'mcp'", proceed to **Install**. Otherwise skip to **Register an upstream**.

## Install

When published to PyPI:
```bash
pipx install 'fieldflow[proxy]' --force
```

From source (until PyPI publish or for development):
```bash
pipx install -e '<path-to-fieldflow-checkout>[proxy]' --force
```

Or directly from a git branch:
```bash
pipx install 'fieldflow[proxy] @ git+https://github.com/<owner>/fieldflow.git@<branch>' --force
```

Verify:
```bash
fieldflow mcp --help
```

## Register an upstream

Ask the user which upstream MCP they want first. Common HTTP+OAuth options:

| Upstream | URL | Auth server |
|---|---|---|
| PostHog | `https://mcp.posthog.com/mcp` | `oauth.posthog.com` |

For HTTP+OAuth (browser handshake, tokens stored in OS keychain):
```bash
fieldflow mcp add <namespace> --url <url>
```

Add `--no-browser` if running over SSH or in a headless environment — fieldflow will print the authorization URL instead of opening a browser.

For stdio upstreams (locally-spawned MCP servers like `npx`):
```bash
fieldflow mcp add <namespace> --command 'npx -y @some-org/mcp' --env API_KEY=...
```

The `<namespace>` becomes the prefix for every tool from that upstream (e.g. `posthog__query_run`, `posthog__insight_create`).

## Wire into Claude Code

```bash
claude mcp add fieldflow -- fieldflow mcp serve
```

Then run `/mcp` inside Claude Code (or restart) to confirm `fieldflow` shows as connected. All upstream tools should appear as `<namespace>__<tool>` and each will accept an optional `fields` array — dot-path selectors like `["data.results[].id", "meta.total"]` to keep only the JSON paths the agent actually needs.

## Validate the savings

Pick one tool from a registered upstream and call it twice — once without `fields` and once with a tight selector. Compare response sizes. Filtered responses on data-heavy tools (queries, lists, dashboards) typically shrink 5-50×.

## Day-2 ops

| Task | Command |
|---|---|
| List registered upstreams | `fieldflow mcp list` |
| Re-authorize after token expiry / revocation | `fieldflow mcp reauth <namespace>` |
| Remove an upstream + clear its tokens | `fieldflow mcp remove <namespace>` |

Registry metadata lives at `~/.config/fieldflow/proxy.json` (perms 0600, no secrets in this file). OAuth tokens live in the OS keychain under the `fieldflow-mcp` service.

## When NOT to use this skill

- The user just wants to call an MCP directly with no field filtering — they should add it to Claude Code natively, not through fieldflow.
- The upstream MCP returns only prose / markdown content (no JSON) — fieldflow can't filter that and adds overhead with no payoff.
- The user wants to reduce CLI output (not MCP output) — use `fieldflow-cli` instead.
