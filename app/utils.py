from __future__ import annotations

from typing import Optional


def extract_base_url(spec: dict) -> Optional[str]:
    """Return the first server URL defined in the OpenAPI spec if available."""

    servers = spec.get("servers")
    if isinstance(servers, list):
        for server in servers:
            if not isinstance(server, dict):
                continue
            url = server.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None
