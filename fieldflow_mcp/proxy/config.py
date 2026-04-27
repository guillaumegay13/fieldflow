"""Registry of upstream MCP servers wrapped by the FieldFlow proxy.

Stored as JSON at ``~/.config/fieldflow/proxy.json`` (or the path from
``FIELDFLOW_CONFIG_HOME``). Secrets never live here — only metadata. Tokens
go to the OS keychain via :mod:`fieldflow_mcp.proxy.tokens`.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

Transport = Literal["http", "stdio"]

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def default_config_path() -> Path:
    base = os.environ.get("FIELDFLOW_CONFIG_HOME")
    if base:
        return Path(base) / "proxy.json"
    return Path.home() / ".config" / "fieldflow" / "proxy.json"


@dataclass
class UpstreamEntry:
    namespace: str
    transport: Transport
    url: Optional[str] = None
    command: Optional[list[str]] = None
    env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _NAMESPACE_RE.match(self.namespace):
            raise ValueError(
                f"Invalid namespace '{self.namespace}': must match {_NAMESPACE_RE.pattern}"
            )
        if self.transport == "http":
            if not self.url:
                raise ValueError(f"Upstream '{self.namespace}': http transport requires url")
        elif self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"Upstream '{self.namespace}': stdio transport requires command"
                )
        else:
            raise ValueError(f"Unknown transport '{self.transport}'")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "namespace": self.namespace,
            "transport": self.transport,
        }
        if self.url is not None:
            out["url"] = self.url
        if self.command is not None:
            out["command"] = list(self.command)
        if self.env:
            out["env"] = dict(self.env)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpstreamEntry":
        return cls(
            namespace=data["namespace"],
            transport=data["transport"],
            url=data.get("url"),
            command=list(data["command"]) if data.get("command") else None,
            env=dict(data.get("env") or {}),
        )


@dataclass
class Registry:
    upstreams: dict[str, UpstreamEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Registry":
        path = path or default_config_path()
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        upstreams = {
            entry["namespace"]: UpstreamEntry.from_dict(entry)
            for entry in raw.get("upstreams", [])
        }
        return cls(upstreams=upstreams)

    def save(self, path: Optional[Path] = None) -> None:
        path = path or default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "upstreams": [entry.to_dict() for entry in self.upstreams.values()],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def add(self, entry: UpstreamEntry) -> None:
        if entry.namespace in self.upstreams:
            raise ValueError(f"Upstream '{entry.namespace}' already exists")
        self.upstreams[entry.namespace] = entry

    def remove(self, namespace: str) -> UpstreamEntry:
        if namespace not in self.upstreams:
            raise KeyError(f"Upstream '{namespace}' not found")
        return self.upstreams.pop(namespace)

    def get(self, namespace: str) -> UpstreamEntry:
        if namespace not in self.upstreams:
            raise KeyError(f"Upstream '{namespace}' not found")
        return self.upstreams[namespace]
