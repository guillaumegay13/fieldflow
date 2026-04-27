"""``fieldflow init``: detect the user's harness, optionally migrate existing
MCP servers behind FieldFlow, and wire FieldFlow in as a single MCP entry.

v1 supports the Claude Code harness only. The flow:

1. Read the user's existing MCP entries (project + local scope from
   ``~/.claude.json``; project-scope from ``./.mcp.json`` if present).
2. Skip entries managed elsewhere (``plugin:*``, ``claude.ai *``).
3. Prompt to migrate each remaining entry. For stdio entries the
   command/args/env are copied; for HTTP entries we drive a fresh OAuth
   handshake (Claude Code's tokens live in a different keystore and are not
   transferable).
4. Remove the migrated entries from Claude Code via ``claude mcp remove``
   and add a single ``fieldflow`` entry pointing at ``fieldflow mcp serve``.

A backup of the original config is written to
``~/.config/fieldflow/init-backup-<timestamp>.json`` before any change.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .config import Registry, UpstreamEntry, default_config_path

CC_CONFIG = Path.home() / ".claude.json"
SKIP_PREFIXES = ("plugin:", "claude.ai ")
FIELDFLOW_NAME = "fieldflow"


@dataclass
class CCEntry:
    """One MCP server entry as Claude Code stores it."""

    name: str
    scope: str  # "local" | "project" | "user"
    config: dict[str, Any]

    @property
    def transport(self) -> str:
        if self.config.get("type") in ("http", "sse"):
            return "http"
        if self.config.get("url"):
            return "http"
        return "stdio"

    @property
    def url(self) -> Optional[str]:
        return self.config.get("url")

    @property
    def command(self) -> Optional[list[str]]:
        cmd = self.config.get("command")
        if cmd is None:
            return None
        args = self.config.get("args") or []
        return [cmd, *args]

    @property
    def env(self) -> dict[str, str]:
        return dict(self.config.get("env") or {})

    @property
    def is_migratable(self) -> bool:
        if self.name == FIELDFLOW_NAME:
            return False
        if any(self.name.startswith(p) for p in SKIP_PREFIXES):
            return False
        return True


def _safe_namespace(name: str) -> str:
    """Coerce an arbitrary MCP name into a fieldflow namespace
    (``[a-z][a-z0-9_]*``)."""

    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip("_")
    if not s:
        return "ns"
    if not s[0].isalpha():
        s = "ns_" + s
    return s


def _read_cc_config() -> dict[str, Any]:
    if not CC_CONFIG.exists():
        return {}
    return json.loads(CC_CONFIG.read_text())


def _read_project_mcp_json(cwd: Path) -> dict[str, Any]:
    p = cwd / ".mcp.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _collect_entries(cwd: Path) -> list[CCEntry]:
    """Gather migratable MCP entries from Claude Code state."""

    entries: list[CCEntry] = []
    seen: set[tuple[str, str]] = set()

    cc = _read_cc_config()
    project_block = (cc.get("projects") or {}).get(str(cwd)) or {}
    for name, cfg in (project_block.get("mcpServers") or {}).items():
        if (name, "local") not in seen:
            entries.append(CCEntry(name=name, scope="local", config=cfg))
            seen.add((name, "local"))

    for name, cfg in (cc.get("mcpServers") or {}).items():
        if (name, "user") not in seen:
            entries.append(CCEntry(name=name, scope="user", config=cfg))
            seen.add((name, "user"))

    project_file = _read_project_mcp_json(cwd)
    for name, cfg in (project_file.get("mcpServers") or {}).items():
        if (name, "project") not in seen:
            entries.append(CCEntry(name=name, scope="project", config=cfg))
            seen.add((name, "project"))

    return entries


def _backup_cc_config(timestamp: str) -> Optional[Path]:
    if not CC_CONFIG.exists():
        return None
    backup_dir = default_config_path().parent
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"init-backup-{timestamp}.json"
    shutil.copy2(CC_CONFIG, target)
    return target


def _claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def _claude_run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["claude", *args],
        check=False,
        text=True,
        capture_output=True,
    )


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    resp = input(question + suffix).strip().lower()
    if not resp:
        return default
    return resp.startswith("y")


def _add_fieldflow_to_cc(scope: str = "local") -> bool:
    """Idempotent: if 'fieldflow' is already registered, do nothing."""

    existing = _claude_run(["mcp", "list"])
    if FIELDFLOW_NAME in (existing.stdout or ""):
        return False
    proc = _claude_run(
        ["mcp", "add", "-s", scope, FIELDFLOW_NAME, "--", "fieldflow", "mcp", "serve"]
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"`claude mcp add fieldflow` failed: {proc.stderr or proc.stdout}"
        )
    return True


def _remove_from_cc(name: str, scope: str) -> None:
    proc = _claude_run(["mcp", "remove", "-s", scope, name])
    if proc.returncode != 0:
        # Best-effort; surface but don't abort the rest of the migration.
        print(
            f"  warning: could not remove '{name}' from Claude Code: "
            f"{proc.stderr.strip() or proc.stdout.strip()}",
            file=sys.stderr,
        )


def _migrate_one(
    entry: CCEntry,
    registry: Registry,
    *,
    open_browser: bool,
) -> tuple[UpstreamEntry, bool]:
    """Build a fieldflow UpstreamEntry from a CC entry. Returns
    ``(entry, needs_oauth)``."""

    namespace = _safe_namespace(entry.name)
    if namespace in registry.upstreams:
        raise ValueError(
            f"Namespace '{namespace}' already exists in fieldflow registry"
        )

    if entry.transport == "http":
        if not entry.url:
            raise ValueError(f"'{entry.name}' has no url")
        upstream = UpstreamEntry(
            namespace=namespace, transport="http", url=entry.url
        )
        return upstream, True

    if not entry.command:
        raise ValueError(f"'{entry.name}' has no command")
    upstream = UpstreamEntry(
        namespace=namespace,
        transport="stdio",
        command=entry.command,
        env=entry.env,
    )
    return upstream, False


async def _drive_oauth(entry: UpstreamEntry, open_browser: bool) -> None:
    from .cli import _drive_oauth_handshake  # avoid circular import at module load

    await _drive_oauth_handshake(entry, open_browser=open_browser, scope=None)


def cmd_init(
    *,
    dry_run: bool = False,
    non_interactive: bool = False,
    no_browser: bool = False,
    cwd: Optional[Path] = None,
) -> int:
    cwd = cwd or Path.cwd()

    if not _claude_cli_available():
        print(
            "Could not find the `claude` CLI on PATH. Install Claude Code or "
            "add it to PATH, then re-run `fieldflow init`.",
            file=sys.stderr,
        )
        return 1

    entries = _collect_entries(cwd)
    migratable = [e for e in entries if e.is_migratable]
    skipped = [e for e in entries if not e.is_migratable]

    print(f"Project: {cwd}")
    print(f"Discovered {len(entries)} MCP server(s) in Claude Code config.")
    if skipped:
        print(
            f"  Skipping {len(skipped)} managed entries: "
            + ", ".join(e.name for e in skipped)
        )
    if not migratable:
        print("Nothing to migrate. Will just register fieldflow with Claude Code.")
    else:
        print("\nMigratable entries:")
        for e in migratable:
            detail = e.url if e.transport == "http" else " ".join(e.command or [])
            print(f"  - {e.name} ({e.scope}, {e.transport}): {detail}")

    if dry_run:
        print("\n--dry-run: nothing changed.")
        return 0

    selected: list[CCEntry] = []
    if migratable:
        if non_interactive:
            selected = list(migratable)
        else:
            print()
            for e in migratable:
                if _prompt_yes_no(f"Migrate '{e.name}' behind fieldflow?", default=True):
                    selected.append(e)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = _backup_cc_config(timestamp)
    if backup:
        print(f"\nBacked up Claude Code config to {backup}")

    registry = Registry.load()

    for cc_entry in selected:
        try:
            upstream, needs_oauth = _migrate_one(
                cc_entry, registry, open_browser=not no_browser
            )
        except ValueError as exc:
            print(f"  skip '{cc_entry.name}': {exc}", file=sys.stderr)
            continue

        if needs_oauth:
            print(f"\nAuthorizing '{cc_entry.name}' as namespace '{upstream.namespace}'…")
            try:
                asyncio.run(_drive_oauth(upstream, open_browser=not no_browser))
            except Exception as exc:
                print(
                    f"  OAuth failed for '{cc_entry.name}': {exc}", file=sys.stderr
                )
                print("  Skipping; you can retry later with `fieldflow mcp add`.")
                continue

        registry.add(upstream)
        registry.save()
        _remove_from_cc(cc_entry.name, cc_entry.scope)
        print(
            f"  migrated '{cc_entry.name}' → fieldflow upstream '{upstream.namespace}'"
        )

    added = _add_fieldflow_to_cc(scope="local")
    if added:
        print("\nRegistered fieldflow with Claude Code (scope=local).")
    else:
        print("\nfieldflow already registered with Claude Code; left alone.")

    print("\nDone. Restart Claude Code (or run `/mcp`) to refresh tool list.")
    return 0
